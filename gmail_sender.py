
"""
Gmail CLI sender tool using OAuth2 authentication.
Sends emails via Gmail API with support for attachments and HTML content.
"""

import os
import json
import base64
import mimetypes
import re
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import click
import markdown
from typing import Dict, Optional, Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Gmail API scopes for sending emails, reading profile, settings, and managing drafts
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.settings.basic',
    'https://www.googleapis.com/auth/gmail.compose',  # For creating and updating drafts
    'https://www.googleapis.com/auth/gmail.modify'   # For managing drafts
]

# Configuration management
class GmailConfig:
    """Configuration management for Gmail CLI."""
    
    def __init__(self):
        self.config_dir = Path.home() / '.config' / 'gmail-cli'
        self.default_config_file = self.config_dir / 'config.json'
        self.default_token_file = self.config_dir / 'token.json'
        
        # Legacy paths for backward compatibility
        self.legacy_credentials_file = '/Users/stephanfitzpatrick/Downloads/OAuth Client ID Secret (1).json'
        self.legacy_token_file = Path.cwd() / 'gmail_token.json'
        
        # Default configuration
        self.defaults = {
            'token_file': str(self.default_token_file),
            'client_id': None,
            'client_secret': None,
            'config_dir': str(self.config_dir)
        }
        
    def ensure_config_dir(self) -> None:
        """Create configuration directory if it doesn't exist."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        except PermissionError as e:
            raise click.ClickException(
                f"Cannot create configuration directory {self.config_dir}: {e}"
            )
        except Exception as e:
            raise click.ClickException(
                f"Error creating configuration directory {self.config_dir}: {e}"
            )
    
    def load_config_file(self, config_file: Optional[str] = None) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        config_path = Path(config_file) if config_file else self.default_config_file
        
        if not config_path.exists():
            return {}
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config if isinstance(config, dict) else {}
        except json.JSONDecodeError as e:
            raise click.ClickException(
                f"Invalid JSON in configuration file {config_path}: {e}"
            )
        except Exception as e:
            raise click.ClickException(
                f"Error reading configuration file {config_path}: {e}"
            )
    
    def merge_config(self, 
                    config_file_path: Optional[str] = None,
                    credentials_file: Optional[str] = None,
                    token_file: Optional[str] = None,
                    client_id: Optional[str] = None,
                    client_secret: Optional[str] = None) -> Dict[str, Any]:
        """Merge configuration from file, CLI args, and defaults."""
        # Start with defaults
        config = self.defaults.copy()
        
        # Load from config file (overrides defaults for client_id/secret and token_file only)
        file_config = self.load_config_file(config_file_path)
        # Only allow specific keys from config file (no credentials_file)
        allowed_config_keys = {'token_file', 'client_id', 'client_secret'}
        filtered_file_config = {k: v for k, v in file_config.items() if k in allowed_config_keys}
        config.update(filtered_file_config)
        
        # CLI arguments override everything
        if token_file is not None:
            config['token_file'] = token_file
        if client_id is not None:
            config['client_id'] = client_id
        if client_secret is not None:
            config['client_secret'] = client_secret
        
        # Credentials file is CLI-only, but add to config for authentication logic
        config['credentials_file'] = credentials_file
            
        # Handle backward compatibility for credentials file (only if no CLI credentials_file provided)
        if not config['credentials_file'] and not (config['client_id'] and config['client_secret']):
            if Path(self.legacy_credentials_file).exists():
                config['credentials_file'] = self.legacy_credentials_file
                click.echo(f"⚠️  Using legacy credentials file: {self.legacy_credentials_file}", err=True)
                click.echo(f"   Consider using --client-id and --client-secret instead", err=True)
        
        return config
    
    def validate_config(self, config: Dict[str, Any]) -> None:
        """Validate the final configuration."""
        # Must have either credentials file OR client_id+client_secret
        has_credentials_file = config.get('credentials_file') and Path(config['credentials_file']).exists()
        has_client_credentials = config.get('client_id') and config.get('client_secret')
        
        if not has_credentials_file and not has_client_credentials:
            error_msg = (
                "Authentication configuration missing. You must provide either:\n"
                "  1. Credentials file via --credentials-file (CLI argument only)\n"
                "  2. Client ID and secret via --client-id and --client-secret (CLI args or config file)\n\n"
                f"For option 1: Download OAuth credentials from Google Cloud Console\n"
                f"For option 2: Get client credentials from your Google Cloud project"
            )
            raise click.ClickException(error_msg)
        
        # If both provided, credentials file takes precedence
        if has_credentials_file and has_client_credentials:
            click.echo("⚠️  Both credentials file and client ID/secret provided. Using credentials file.", err=True)
    
    def migrate_legacy_token(self, config: Dict[str, Any]) -> None:
        """Migrate legacy token file to new location if needed."""
        if self.legacy_token_file.exists() and not Path(config['token_file']).exists():
            if click.confirm(
                f"\nFound existing token file at {self.legacy_token_file}.\n"
                f"Would you like to migrate it to {config['token_file']}?"
            ):
                try:
                    self.ensure_config_dir()
                    self.legacy_token_file.rename(config['token_file'])
                    click.echo(f"✓ Token file migrated to {config['token_file']}")
                except Exception as e:
                    click.echo(f"⚠️  Could not migrate token file: {e}", err=True)
                    click.echo(f"   You may need to re-authenticate", err=True)


def authenticate_gmail(config: Dict[str, Any]):
    """Authenticate with Gmail API using OAuth2 flow with configurable credentials."""
    creds = None
    token_file = config['token_file']
    
    # Load existing token if available
    if os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        except Exception as e:
            click.echo(f"Error loading existing token: {e}", err=True)
    
    # If there are no valid credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                click.echo("Token refreshed successfully.")
            except Exception as e:
                click.echo(f"Error refreshing token: {e}", err=True)
                creds = None
        
        if not creds:
            # Create OAuth2 flow based on configuration
            try:
                if config.get('credentials_file'):
                    # Use credentials file method
                    if not os.path.exists(config['credentials_file']):
                        raise click.ClickException(
                            f"Credentials file not found at {config['credentials_file']}. "
                            "Please ensure you have downloaded the OAuth client credentials from Google Cloud Console."
                        )
                    flow = InstalledAppFlow.from_client_secrets_file(config['credentials_file'], SCOPES)
                elif config.get('client_id') and config.get('client_secret'):
                    # Use client ID/secret method
                    client_config = {
                        'installed': {
                            'client_id': config['client_id'],
                            'client_secret': config['client_secret'],
                            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                            'token_uri': 'https://oauth2.googleapis.com/token',
                            'redirect_uris': ['http://localhost']
                        }
                    }
                    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
                else:
                    raise click.ClickException(
                        "No valid authentication method configured. Please provide either:\n"
                        "  1. Credentials file via --credentials-file\n"
                        "  2. Client ID and secret via --client-id and --client-secret"
                    )
                
                creds = flow.run_local_server(port=0)
                click.echo("Authentication successful!")
                
            except Exception as e:
                raise click.ClickException(f"Authentication failed: {e}")
        
        # Save the credentials for the next run
        try:
            # Ensure directory exists
            token_path = Path(token_file)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(token_file, 'w') as token:
                token.write(creds.to_json())
        except Exception as e:
            click.echo(f"Warning: Could not save token file: {e}", err=True)
    
    return creds


def create_message(sender, to, subject, body_html, cc=None, bcc=None, signature=''):
    """Create an HTML email message."""
    message = MIMEMultipart()
    message['to'] = ', '.join(to)
    message['from'] = sender
    message['subject'] = subject
    
    if cc:
        message['cc'] = ', '.join(cc)
    if bcc:
        message['bcc'] = ', '.join(bcc)
    
    # Add signature to body if provided
    full_body = body_html
    if signature:
        full_body = f"{body_html}<br><br>{signature}"
    
    # Always send as HTML
    message.attach(MIMEText(full_body, 'html'))
    
    return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}


def create_message_with_attachment(sender, to, subject, body_html, 
                                 cc=None, bcc=None, attachments=None, signature=''):
    """Create an HTML email message with attachments."""
    message = MIMEMultipart()
    message['to'] = ', '.join(to)
    message['from'] = sender
    message['subject'] = subject
    
    if cc:
        message['cc'] = ', '.join(cc)
    if bcc:
        message['bcc'] = ', '.join(bcc)
    
    # Add signature to body if provided
    full_body = body_html
    if signature:
        full_body = f"{body_html}<br><br>{signature}"
    
    # Always send as HTML
    message.attach(MIMEText(full_body, 'html'))
    
    # Add attachments
    if attachments:
        for file_path in attachments:
            if not os.path.isfile(file_path):
                raise click.ClickException(f"Attachment file not found: {file_path}")
            
            content_type, encoding = mimetypes.guess_type(file_path)
            
            if content_type is None or encoding is not None:
                content_type = 'application/octet-stream'
            
            main_type, sub_type = content_type.split('/', 1)
            
            with open(file_path, 'rb') as fp:
                attachment = MIMEBase(main_type, sub_type)
                attachment.set_payload(fp.read())
                encoders.encode_base64(attachment)
                attachment.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{Path(file_path).name}"'
                )
                message.attach(attachment)
    
    return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}


def send_message(service, user_id, message):
    """Send an email message."""
    try:
        message = service.users().messages().send(userId=user_id, body=message).execute()
        return message
    except HttpError as error:
        if error.resp.status == 403:
            raise click.ClickException(
                "Gmail API access denied. Please check your OAuth consent and API permissions."
            )
        elif error.resp.status == 429:
            raise click.ClickException(
                "Gmail API quota exceeded. Please try again later."
            )
        else:
            raise click.ClickException(f"Gmail API error: {error}")


def get_sender_email(service):
    """Get the authenticated user's email address."""
    try:
        profile = service.users().getProfile(userId='me').execute()
        return profile['emailAddress']
    except HttpError as error:
        raise click.ClickException(f"Could not retrieve sender email: {error}")


def convert_to_html(content, input_format):
    """Convert content to HTML based on input format with enhanced formatting."""
    if input_format == 'html':
        return content
    elif input_format == 'markdown':
        # Use markdown extensions for better code formatting
        html = markdown.markdown(
            content,
            extensions=[
                'codehilite',  # Syntax highlighting
                'fenced_code', # Better fenced code block support
                'tables',      # Table support
                'toc',         # Table of contents
                'nl2br'        # Convert newlines to <br> tags
            ],
            extension_configs={
                'codehilite': {
                    'css_class': 'highlight',
                    'use_pygments': True,
                    'noclasses': True,  # Inline styles for email compatibility
                    'linenos': False    # No line numbers for email
                }
            }
        )
        # Add custom CSS for better email formatting
        css_styles = """
        <style>
        /* Code block styling */
        .highlight {
            background: #f6f8fa !important;
            border: 1px solid #d1d9e0 !important;
            border-radius: 6px !important;
            padding: 16px !important;
            margin: 16px 0 !important;
            overflow-x: auto !important;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace !important;
            font-size: 14px !important;
            line-height: 1.45 !important;
        }
        /* Inline code styling */
        code {
            background: #f6f8fa !important;
            padding: 2px 4px !important;
            border-radius: 3px !important;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace !important;
            font-size: 85% !important;
            color: #d73a49 !important;
        }
        /* Don't style code inside pre blocks */
        pre code {
            background: transparent !important;
            padding: 0 !important;
            border-radius: 0 !important;
            color: inherit !important;
        }
        /* Table styling */
        table {
            border-collapse: collapse !important;
            width: 100% !important;
            margin: 16px 0 !important;
        }
        th, td {
            border: 1px solid #d1d9e0 !important;
            padding: 8px 12px !important;
            text-align: left !important;
        }
        th {
            background: #f6f8fa !important;
            font-weight: bold !important;
        }
        /* Blockquote styling */
        blockquote {
            border-left: 4px solid #d1d9e0 !important;
            padding: 0 16px !important;
            margin: 16px 0 !important;
            color: #6a737d !important;
        }
        </style>
        """
        return css_styles + html
    elif input_format == 'plaintext':
        # Convert plain text to HTML, preserving line breaks
        html_content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        html_content = html_content.replace('\n', '<br>\n')
        return html_content
    else:
        raise ValueError(f"Unsupported input format: {input_format}")


def html_to_plain_text(html):
    """Convert HTML signature to plain text."""
    if not html:
        return ''
    
    # Remove HTML tags but preserve structure
    text = html
    
    # Convert <br> and <br/> tags to newlines
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    
    # Convert <div> tags to newlines (Gmail uses divs for line breaks)
    text = re.sub(r'</div>\s*<div[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?div[^>]*>', '', text, flags=re.IGNORECASE)
    
    # Convert <p> tags to double newlines
    text = re.sub(r'</p>\s*<p[^>]*>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?p[^>]*>', '', text, flags=re.IGNORECASE)
    
    # Extract URLs from <a> tags and format as "text (url)"
    def replace_links(match):
        href = match.group(1)
        link_text = match.group(2)
        if href == link_text or not link_text.strip():
            return href
        return f"{link_text} ({href})"
    
    text = re.sub(r'<a[^>]+href=["\']([^"\'>]+)["\'][^>]*>([^<]*)</a>', replace_links, text, flags=re.IGNORECASE)
    
    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Clean up whitespace
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Multiple newlines to double
    text = re.sub(r'^\s+|\s+$', '', text)  # Trim whitespace
    
    return text


def get_gmail_signature(service):
    """Get the user's default Gmail signature."""
    try:
        # Get the primary send-as address (which contains the signature)
        send_as_list = service.users().settings().sendAs().list(userId='me').execute()
        
        for send_as in send_as_list.get('sendAs', []):
            if send_as.get('isPrimary', False):
                signature = send_as.get('signature', '')
                return signature
        
        # If no primary found, return empty signature
        return ''
    except HttpError as error:
        click.echo(f"Warning: Could not retrieve Gmail signature: {error}", err=True)
        return ''


def create_draft(service, user_id, message):
    """Create a draft email."""
    try:
        draft = service.users().drafts().create(
            userId=user_id, 
            body={'message': message}
        ).execute()
        return draft
    except HttpError as error:
        if error.resp.status == 403:
            raise click.ClickException(
                "Gmail API access denied. Please check your OAuth consent and API permissions."
            )
        elif error.resp.status == 429:
            raise click.ClickException(
                "Gmail API quota exceeded. Please try again later."
            )
        else:
            raise click.ClickException(f"Gmail API error: {error}")


def get_message_details(service, message_id):
    """Retrieve message details including headers and thread ID."""
    try:
        message = service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        ).execute()
        return message
    except HttpError as error:
        if error.resp.status == 404:
            raise click.ClickException(f"Message not found: {message_id}")
        else:
            raise click.ClickException(f"Gmail API error: {error}")


def get_thread_details(service, thread_id):
    """Retrieve full thread context."""
    try:
        thread = service.users().threads().get(
            userId='me',
            id=thread_id
        ).execute()
        return thread
    except HttpError as error:
        if error.resp.status == 404:
            raise click.ClickException(f"Thread not found: {thread_id}")
        else:
            raise click.ClickException(f"Gmail API error: {error}")


def extract_reply_headers(message):
    """Extract necessary headers for reply."""
    headers = {}
    for header in message['payload'].get('headers', []):
        name = header['name'].lower()
        if name in ['message-id', 'from', 'to', 'cc', 'subject', 'references', 'date']:
            headers[name] = header['value']
    return headers


def parse_email_addresses(header_value):
    """Parse email addresses from header value."""
    import email.utils
    addresses = []
    if not header_value:
        return addresses
    for name, addr in email.utils.getaddresses([header_value]):
        if addr:
            addresses.append(addr)
    return addresses


def determine_reply_recipients(original_headers, sender_email, reply_all, additional_to, additional_cc):
    """Determine recipients for reply based on original message."""
    recipients = {'to': [], 'cc': []}
    
    # Parse email addresses from headers
    from_addr = parse_email_addresses(original_headers.get('from', ''))
    to_addrs = parse_email_addresses(original_headers.get('to', ''))
    cc_addrs = parse_email_addresses(original_headers.get('cc', ''))
    
    if reply_all:
        # Reply to sender and all recipients
        recipients['to'] = from_addr[:1] if from_addr else []  # Only first from address
        
        # Add other TO recipients (excluding self)
        for addr in to_addrs:
            if addr.lower() != sender_email.lower() and addr not in recipients['to']:
                recipients['cc'].append(addr)
        
        # Add CC recipients (excluding self)
        for addr in cc_addrs:
            if addr.lower() != sender_email.lower() and addr not in recipients['cc']:
                recipients['cc'].append(addr)
    else:
        # Reply only to sender
        recipients['to'] = from_addr[:1] if from_addr else []
    
    # Add additional recipients
    if additional_to:
        for addr in additional_to:
            if addr not in recipients['to']:
                recipients['to'].append(addr)
    if additional_cc:
        for addr in additional_cc:
            if addr not in recipients['cc']:
                recipients['cc'].append(addr)
    
    return recipients


def extract_message_body(message):
    """Extract the body content from a message."""
    def get_body_from_parts(parts):
        body = ''
        for part in parts:
            if part['mimeType'] == 'text/html':
                data = part['body'].get('data', '')
                if data:
                    body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    return body
            elif part['mimeType'] == 'text/plain' and not body:
                data = part['body'].get('data', '')
                if data:
                    text = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                    body = text.replace('\n', '<br>')
            elif 'parts' in part:
                body = get_body_from_parts(part['parts'])
                if body:
                    return body
        return body
    
    payload = message.get('payload', {})
    if 'parts' in payload:
        return get_body_from_parts(payload['parts'])
    else:
        # Single part message
        data = payload.get('body', {}).get('data', '')
        if data:
            decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            # Check if it's HTML or plain text
            mime_type = payload.get('mimeType', 'text/plain')
            if mime_type == 'text/plain':
                decoded = decoded.replace('\n', '<br>')
            return decoded
    return ''


def format_quoted_message(original_msg):
    """Format original message as quoted text for reply."""
    from datetime import datetime
    
    # Extract message body
    body = extract_message_body(original_msg)
    
    # Get sender and date information
    headers = extract_reply_headers(original_msg)
    from_header = headers.get('from', 'Unknown')
    
    # Parse date from headers if available, otherwise use internal date
    date_header = headers.get('date', '')
    if date_header:
        try:
            # Try to parse the date header
            import email.utils
            date_tuple = email.utils.parsedate_to_datetime(date_header)
            date_str = date_tuple.strftime('%a, %b %d, %Y at %I:%M %p')
        except:
            # Fallback to internal date
            internal_date = original_msg.get('internalDate')
            if internal_date:
                timestamp = datetime.fromtimestamp(int(internal_date) / 1000)
                date_str = timestamp.strftime('%a, %b %d, %Y at %I:%M %p')
            else:
                date_str = 'Unknown date'
    else:
        internal_date = original_msg.get('internalDate')
        if internal_date:
            timestamp = datetime.fromtimestamp(int(internal_date) / 1000)
            date_str = timestamp.strftime('%a, %b %d, %Y at %I:%M %p')
        else:
            date_str = 'Unknown date'
    
    # Format as Gmail-style quoted text
    quoted_html = f"""
    <div class="gmail_quote">
        <div dir="ltr" class="gmail_attr">
            On {date_str}, {from_header} wrote:<br>
        </div>
        <blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204);padding-left:1ex">
            {body}
        </blockquote>
    </div>
    """
    
    return quoted_html


def create_reply_message(original_msg, sender, body_html, 
                        reply_all=False, additional_to=None, 
                        additional_cc=None, additional_bcc=None, 
                        signature='', include_quoted=True):
    """Create a reply message with proper headers and formatting."""
    
    # Extract original message details
    original_headers = extract_reply_headers(original_msg)
    
    message = MIMEMultipart()
    
    # Set threading headers
    if 'message-id' in original_headers:
        message['In-Reply-To'] = original_headers['message-id']
        references = original_headers.get('references', '')
        if references:
            message['References'] = f"{references} {original_headers['message-id']}"
        else:
            message['References'] = original_headers['message-id']
    
    # Determine recipients
    recipients = determine_reply_recipients(
        original_headers, 
        sender, 
        reply_all, 
        additional_to,
        additional_cc
    )
    
    if not recipients['to']:
        raise click.ClickException("No recipients found for reply. Original message may have invalid headers.")
    
    message['to'] = ', '.join(recipients['to'])
    if recipients['cc']:
        message['cc'] = ', '.join(recipients['cc'])
    if additional_bcc:
        message['bcc'] = ', '.join(additional_bcc)
    
    message['from'] = sender
    
    # Handle subject (add Re: if not present)
    original_subject = original_headers.get('subject', '')
    if not original_subject.lower().startswith('re: '):
        message['subject'] = f"Re: {original_subject}"
    else:
        message['subject'] = original_subject
    
    # Build reply body with quoted text
    if include_quoted:
        quoted_text = format_quoted_message(original_msg)
        full_body = f"{body_html}{signature}<br><br>{quoted_text}"
    else:
        full_body = f"{body_html}{signature}"
    
    message.attach(MIMEText(full_body, 'html'))
    
    raw_message = {
        'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()
    }
    
    # Preserve thread ID
    thread_id = original_msg.get('threadId')
    if thread_id:
        raw_message['threadId'] = thread_id
    
    return raw_message


def create_reply_message_with_attachment(original_msg, sender, body_html,
                                        reply_all=False, additional_to=None,
                                        additional_cc=None, additional_bcc=None,
                                        attachments=None, signature='', include_quoted=True):
    """Create a reply message with attachments."""
    
    # Extract original message details
    original_headers = extract_reply_headers(original_msg)
    
    message = MIMEMultipart()
    
    # Set threading headers
    if 'message-id' in original_headers:
        message['In-Reply-To'] = original_headers['message-id']
        references = original_headers.get('references', '')
        if references:
            message['References'] = f"{references} {original_headers['message-id']}"
        else:
            message['References'] = original_headers['message-id']
    
    # Determine recipients
    recipients = determine_reply_recipients(
        original_headers, 
        sender, 
        reply_all, 
        additional_to,
        additional_cc
    )
    
    if not recipients['to']:
        raise click.ClickException("No recipients found for reply. Original message may have invalid headers.")
    
    message['to'] = ', '.join(recipients['to'])
    if recipients['cc']:
        message['cc'] = ', '.join(recipients['cc'])
    if additional_bcc:
        message['bcc'] = ', '.join(additional_bcc)
    
    message['from'] = sender
    
    # Handle subject (add Re: if not present)
    original_subject = original_headers.get('subject', '')
    if not original_subject.lower().startswith('re: '):
        message['subject'] = f"Re: {original_subject}"
    else:
        message['subject'] = original_subject
    
    # Build reply body with quoted text
    if include_quoted:
        quoted_text = format_quoted_message(original_msg)
        full_body = f"{body_html}{signature}<br><br>{quoted_text}"
    else:
        full_body = f"{body_html}{signature}"
    
    message.attach(MIMEText(full_body, 'html'))
    
    # Add attachments
    if attachments:
        for file_path in attachments:
            if not os.path.isfile(file_path):
                raise click.ClickException(f"Attachment file not found: {file_path}")
            
            content_type, encoding = mimetypes.guess_type(file_path)
            
            if content_type is None or encoding is not None:
                content_type = 'application/octet-stream'
            
            main_type, sub_type = content_type.split('/', 1)
            
            with open(file_path, 'rb') as fp:
                attachment = MIMEBase(main_type, sub_type)
                attachment.set_payload(fp.read())
                encoders.encode_base64(attachment)
                attachment.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{Path(file_path).name}"'
                )
                message.attach(attachment)
    
    raw_message = {
        'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()
    }
    
    # Preserve thread ID
    thread_id = original_msg.get('threadId')
    if thread_id:
        raw_message['threadId'] = thread_id
    
    return raw_message












# Configuration options shared by all commands
def add_config_options(func):
    """Add common configuration options to a command."""
    func = click.option('--config-file', type=click.Path(),
                       help='Path to configuration JSON file with client_id/secret/token_file (default: ~/.config/gmail-cli/config.json)')(func)
    func = click.option('--client-secret', 
                       help='OAuth2 client secret (can be set via CLI or config file)')(func)
    func = click.option('--client-id', 
                       help='OAuth2 client ID (can be set via CLI or config file)')(func)
    func = click.option('--token-file', type=click.Path(),
                       help='Path to store/read OAuth2 token (default: ~/.config/gmail-cli/token.json)')(func)
    func = click.option('--credentials-file', type=click.Path(exists=True),
                       help='Path to OAuth2 credentials JSON file (CLI only, not supported in config file)')(func)
    return func


@click.group()
def cli():
    """Gmail CLI - Send emails and manage drafts via Gmail API."""
    pass


@cli.command()
@click.option('--draft-id', required=True, help='Draft ID to send')
@add_config_options
def send(draft_id, credentials_file, token_file, client_id, client_secret, config_file):
    """Send an existing draft."""
    
    # Initialize configuration system
    gmail_config = GmailConfig()
    
    try:
        # Ensure config directory exists
        gmail_config.ensure_config_dir()
        
        # Merge configuration from file, CLI args, and defaults
        config = gmail_config.merge_config(
            config_file_path=config_file,
            credentials_file=credentials_file,
            token_file=token_file,
            client_id=client_id,
            client_secret=client_secret
        )
        
        # Validate configuration
        gmail_config.validate_config(config)
        
        # Handle legacy token migration
        gmail_config.migrate_legacy_token(config)
        
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Configuration error: {e}")
    
    try:
        # Authenticate and build service
        click.echo("\nAuthenticating with Gmail...")
        creds = authenticate_gmail(config)
        service = build('gmail', 'v1', credentials=creds)
        
        click.echo(f"Sending draft {draft_id}...")
        
        # Send the draft using Gmail API
        result = service.users().drafts().send(
            userId='me',
            body={'id': draft_id}
        ).execute()
        
        click.echo(f"✓ Draft sent successfully! Message ID: {result['id']}")
        
    except HttpError as error:
        if error.resp.status == 404:
            raise click.ClickException(f"Draft not found: {draft_id}")
        elif error.resp.status == 403:
            raise click.ClickException(
                "Gmail API access denied. Please check your OAuth consent and API permissions."
            )
        elif error.resp.status == 429:
            raise click.ClickException(
                "Gmail API quota exceeded. Please try again later."
            )
        else:
            raise click.ClickException(f"Gmail API error: {error}")
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Unexpected error: {e}")


@cli.command()
@click.option('--to', multiple=True, required=True, 
              help='Recipient email addresses (can be used multiple times)')
@click.option('--subject', required=True, help='Email subject')
@click.option('--body', help='Email body text')
@click.option('--body-file', type=click.Path(exists=True), 
              help='Read email body from file')
@click.option('--input-format', type=click.Choice(['markdown', 'html', 'plaintext']), 
              default='markdown', help='Input format for email body (default: markdown)')
@click.option('--cc', multiple=True, help='CC email addresses')
@click.option('--bcc', multiple=True, help='BCC email addresses')
@click.option('--attachment', multiple=True, type=click.Path(exists=True),
              help='File paths to attach (can be used multiple times)')
@click.option('--sender', help='Override sender email (if permitted)')
@click.option('--signature/--no-signature', default=True, 
              help='Include Gmail default signature (default: enabled)')
@add_config_options
def draft(to, subject, body, body_file, input_format, cc, bcc, attachment, sender, signature,
          credentials_file, token_file, client_id, client_secret, config_file):
    """Create a draft email."""
    
    # Initialize configuration system
    gmail_config = GmailConfig()
    
    try:
        # Ensure config directory exists
        gmail_config.ensure_config_dir()
        
        # Merge configuration from file, CLI args, and defaults
        config = gmail_config.merge_config(
            config_file_path=config_file,
            credentials_file=credentials_file,
            token_file=token_file,
            client_id=client_id,
            client_secret=client_secret
        )
        
        # Validate configuration
        gmail_config.validate_config(config)
        
        # Handle legacy token migration
        gmail_config.migrate_legacy_token(config)
        
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Configuration error: {e}")
    
    # Validate input
    if not body and not body_file:
        raise click.ClickException("Either --body or --body-file must be provided")
    
    if body and body_file:
        raise click.ClickException("Cannot specify both --body and --body-file")
    
    # Read body from file if specified
    if body_file:
        try:
            with open(body_file, 'r', encoding='utf-8') as f:
                body = f.read()
        except Exception as e:
            raise click.ClickException(f"Error reading body file: {e}")
    
    try:
        # Authenticate and build service
        click.echo("\nAuthenticating with Gmail...")
        creds = authenticate_gmail(config)
        service = build('gmail', 'v1', credentials=creds)
        
        # Get sender email if not provided
        if not sender:
            sender = get_sender_email(service)
        
        click.echo(f"Creating draft from: {sender}")
        
        # Convert body to HTML based on input format
        click.echo(f"Converting {input_format} content to HTML...")
        body_html = convert_to_html(body, input_format)
        
        # Get Gmail signature if requested
        gmail_signature = ''
        if signature:
            click.echo("Retrieving Gmail signature...")
            gmail_signature = get_gmail_signature(service)
            if gmail_signature:
                click.echo("✓ Gmail signature retrieved")
            else:
                click.echo("! No Gmail signature found")
        
        # Create message
        if attachment:
            click.echo(f"Creating HTML draft with {len(attachment)} attachment(s)...")
            message = create_message_with_attachment(
                sender, list(to), subject, body_html, 
                list(cc) if cc else None, 
                list(bcc) if bcc else None, 
                list(attachment),
                gmail_signature
            )
        else:
            click.echo("Creating HTML draft...")
            message = create_message(
                sender, list(to), subject, body_html,
                list(cc) if cc else None,
                list(bcc) if bcc else None,
                gmail_signature
            )
        
        # Create draft
        click.echo("Creating draft...")
        draft = create_draft(service, 'me', message)
        draft_id = draft['id']
        
        click.echo(f"✓ Draft created successfully!")
        click.echo(f"  Draft ID: {draft_id}")
        click.echo(f"  Subject: {subject}")
        click.echo(f"  To: {', '.join(to)}")
        click.echo(f"\nTo send this draft, use: gmail-cli send --draft-id {draft_id}")
        
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Unexpected error: {e}")


@cli.command()
@click.option('--message-id', help='Message ID to reply to')
@click.option('--thread-id', help='Thread ID to reply to (uses latest message)')
@click.option('--body', help='Reply body text')
@click.option('--body-file', type=click.Path(exists=True), 
              help='Read reply body from file')
@click.option('--input-format', type=click.Choice(['markdown', 'html', 'plaintext']), 
              default='markdown', help='Input format for reply body')
@click.option('--reply-all', is_flag=True, help='Reply to all recipients')
@click.option('--to', multiple=True, help='Additional TO recipients')
@click.option('--cc', multiple=True, help='Additional CC recipients')
@click.option('--bcc', multiple=True, help='BCC recipients')
@click.option('--attachment', multiple=True, type=click.Path(exists=True),
              help='File paths to attach')
@click.option('--no-quote', is_flag=True, help='Don\'t include quoted original message')
@click.option('--signature/--no-signature', default=True, 
              help='Include Gmail default signature')
@add_config_options
def reply(message_id, thread_id, body, body_file, input_format, reply_all,
          to, cc, bcc, attachment, no_quote, signature,
          credentials_file, token_file, client_id, client_secret, config_file):
    """Reply to an existing email message or thread. Creates a draft reply."""
    
    # Validate input
    if not message_id and not thread_id:
        raise click.ClickException("Either --message-id or --thread-id must be provided")
    
    if message_id and thread_id:
        raise click.ClickException("Cannot specify both --message-id and --thread-id")
    
    if not body and not body_file:
        raise click.ClickException("Either --body or --body-file must be provided")
    
    if body and body_file:
        raise click.ClickException("Cannot specify both --body and --body-file")
    
    # Initialize configuration system
    gmail_config = GmailConfig()
    
    try:
        # Ensure config directory exists
        gmail_config.ensure_config_dir()
        
        # Merge configuration from file, CLI args, and defaults
        config = gmail_config.merge_config(
            config_file_path=config_file,
            credentials_file=credentials_file,
            token_file=token_file,
            client_id=client_id,
            client_secret=client_secret
        )
        
        # Validate configuration
        gmail_config.validate_config(config)
        
        # Handle legacy token migration
        gmail_config.migrate_legacy_token(config)
        
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Configuration error: {e}")
    
    # Read body from file if specified
    if body_file:
        try:
            with open(body_file, 'r', encoding='utf-8') as f:
                body = f.read()
        except Exception as e:
            raise click.ClickException(f"Error reading body file: {e}")
    
    try:
        # Authenticate and build service
        click.echo("\nAuthenticating with Gmail...")
        creds = authenticate_gmail(config)
        service = build('gmail', 'v1', credentials=creds)
        
        # Get original message
        if message_id:
            click.echo(f"Retrieving message {message_id}...")
            original_msg = get_message_details(service, message_id)
        else:
            # Get latest message from thread
            click.echo(f"Retrieving thread {thread_id}...")
            thread = get_thread_details(service, thread_id)
            messages = thread.get('messages', [])
            if not messages:
                raise click.ClickException(f"No messages found in thread {thread_id}")
            original_msg = messages[-1]  # Reply to latest message
            message_id = original_msg['id']
            click.echo(f"Replying to latest message in thread: {message_id}")
        
        # Get sender email
        sender = get_sender_email(service)
        click.echo(f"Creating reply from: {sender}")
        
        # Convert body to HTML
        click.echo(f"Converting {input_format} content to HTML...")
        body_html = convert_to_html(body, input_format)
        
        # Get signature if requested
        gmail_signature = ''
        if signature:
            click.echo("Retrieving Gmail signature...")
            gmail_signature = get_gmail_signature(service)
            if gmail_signature:
                click.echo("✓ Gmail signature retrieved")
            else:
                click.echo("! No Gmail signature found")
        
        # Create reply message
        if attachment:
            click.echo(f"Creating reply draft with {len(attachment)} attachment(s)...")
            message = create_reply_message_with_attachment(
                original_msg, sender, body_html, reply_all,
                list(to) if to else None,
                list(cc) if cc else None,
                list(bcc) if bcc else None,
                list(attachment),
                gmail_signature,
                not no_quote
            )
        else:
            click.echo("Creating reply draft...")
            message = create_reply_message(
                original_msg, sender, body_html, reply_all,
                list(to) if to else None,
                list(cc) if cc else None,
                list(bcc) if bcc else None,
                gmail_signature,
                not no_quote
            )
        
        # Always create a draft (never send immediately)
        click.echo("Creating draft...")
        draft = create_draft(service, 'me', message)
        draft_id = draft['id']
        
        click.echo(f"✓ Reply draft created successfully!")
        click.echo(f"  Draft ID: {draft_id}")
        click.echo(f"  Thread: {original_msg.get('threadId')}")
        
        # Extract and display reply details
        headers = extract_reply_headers(original_msg)
        original_subject = headers.get('subject', 'No subject')
        reply_subject = f"Re: {original_subject}" if not original_subject.lower().startswith('re: ') else original_subject
        
        click.echo(f"  Subject: {reply_subject}")
        
        # Show recipient summary
        if reply_all:
            click.echo(f"  Reply mode: Reply All")
        else:
            click.echo(f"  Reply mode: Reply to sender")
        
        click.echo(f"\nTo send this reply, use: gmail-cli send --draft-id {draft_id}")
        
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Unexpected error: {e}")


if __name__ == '__main__':
    cli()
