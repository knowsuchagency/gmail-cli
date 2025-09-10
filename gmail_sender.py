
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
from datetime import datetime

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


def list_user_drafts(service, user_id='me', max_results=10):
    """List user's drafts."""
    try:
        response = service.users().drafts().list(
            userId=user_id,
            maxResults=max_results
        ).execute()
        drafts = response.get('drafts', [])
        
        # Get details for each draft
        draft_details = []
        for draft in drafts:
            try:
                draft_data = service.users().drafts().get(
                    userId=user_id, 
                    id=draft['id']
                ).execute()
                message = draft_data['message']
                headers = {h['name']: h['value'] for h in message['payload'].get('headers', [])}
                draft_details.append({
                    'id': draft['id'],
                    'subject': headers.get('Subject', '(no subject)'),
                    'to': headers.get('To', ''),
                    'date': headers.get('Date', '')
                })
            except HttpError:
                continue
        
        return draft_details
    except HttpError as error:
        raise click.ClickException(f"Error listing drafts: {error}")


def update_draft(service, user_id, draft_id, message):
    """Update an existing draft."""
    try:
        draft = service.users().drafts().update(
            userId=user_id,
            id=draft_id,
            body={'message': message}
        ).execute()
        return draft
    except HttpError as error:
        if error.resp.status == 404:
            raise click.ClickException(f"Draft not found: {draft_id}")
        else:
            raise click.ClickException(f"Error updating draft: {error}")


def send_draft_message(service, user_id, draft_id):
    """Send an existing draft."""
    try:
        message = service.users().drafts().send(
            userId=user_id,
            body={'id': draft_id}
        ).execute()
        return message
    except HttpError as error:
        if error.resp.status == 404:
            raise click.ClickException(f"Draft not found: {draft_id}")
        else:
            raise click.ClickException(f"Error sending draft: {error}")


def get_draft_store_path():
    """Get the path to the draft ID storage file."""
    config_dir = Path.home() / '.config' / 'gmail-cli'
    return config_dir / 'drafts.json'


def save_draft_id(draft_id, subject, to):
    """Save draft ID to local storage for easy reference."""
    store_path = get_draft_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing drafts
    drafts = {}
    if store_path.exists():
        try:
            with open(store_path, 'r') as f:
                drafts = json.load(f)
        except (json.JSONDecodeError, IOError):
            drafts = {}
    
    # Add new draft
    drafts[draft_id] = {
        'subject': subject,
        'to': to,
        'created': datetime.now().isoformat()
    }
    
    # Save back
    with open(store_path, 'w') as f:
        json.dump(drafts, f, indent=2)


def load_draft_ids():
    """Load saved draft IDs from local storage."""
    store_path = get_draft_store_path()
    if not store_path.exists():
        return {}
    
    try:
        with open(store_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def remove_draft_id(draft_id):
    """Remove a draft ID from local storage."""
    store_path = get_draft_store_path()
    if not store_path.exists():
        return
    
    drafts = load_draft_ids()
    if draft_id in drafts:
        del drafts[draft_id]
        with open(store_path, 'w') as f:
            json.dump(drafts, f, indent=2)


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
@click.option('--draft-id', help='Send an existing draft instead of creating new email')
@add_config_options
def send(to, subject, body, body_file, input_format, cc, bcc, attachment, sender, signature,
         draft_id, credentials_file, token_file, client_id, client_secret, config_file):
    """Send an email via Gmail API or send an existing draft."""
    
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
    
    # If draft_id provided, send existing draft
    if draft_id:
        try:
            # Authenticate and build service
            click.echo("\nAuthenticating with Gmail...")
            creds = authenticate_gmail(config)
            service = build('gmail', 'v1', credentials=creds)
            
            click.echo(f"Sending draft {draft_id}...")
            result = send_draft_message(service, 'me', draft_id)
            
            # Remove from local storage
            remove_draft_id(draft_id)
            
            click.echo(f"✓ Draft sent successfully! Message ID: {result['id']}")
            return
        except click.ClickException:
            raise
        except Exception as e:
            raise click.ClickException(f"Unexpected error sending draft: {e}")
    
    # Validate input for new email
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
    
    # Warn user if using plaintext with signature
    if input_format == 'plaintext' and signature:
        click.echo("\n⚠️  WARNING: You are using plaintext input format with Gmail signature enabled.", err=True)
        click.echo("Your Gmail signature is in HTML format and will be converted to plain text.", err=True)
        click.echo("This may result in suboptimal formatting (links will show as 'text (url)').", err=True)
        click.echo("\nRecommended alternatives:", err=True)
        click.echo("  1. Use --input-format=markdown (default) for better formatting", err=True)
        click.echo("  2. Use --input-format=html if your content is already HTML", err=True)
        click.echo("  3. Use --no-signature to disable signature", err=True)
        
        if not click.confirm("\nDo you want to continue with plaintext + signature conversion?"):
            raise click.Abort()
    
    try:
        # Authenticate and build service
        click.echo("\nAuthenticating with Gmail...")
        creds = authenticate_gmail(config)
        service = build('gmail', 'v1', credentials=creds)
        
        # Get sender email if not provided
        if not sender:
            sender = get_sender_email(service)
        
        click.echo(f"Sending email from: {sender}")
        
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
            click.echo(f"Creating HTML email with {len(attachment)} attachment(s)...")
            message = create_message_with_attachment(
                sender, list(to), subject, body_html, 
                list(cc) if cc else None, 
                list(bcc) if bcc else None, 
                list(attachment),
                gmail_signature
            )
        else:
            click.echo("Creating HTML email...")
            message = create_message(
                sender, list(to), subject, body_html,
                list(cc) if cc else None,
                list(bcc) if bcc else None,
                gmail_signature
            )
        
        # Send message
        click.echo("Sending email...")
        result = send_message(service, 'me', message)
        
        click.echo(f"✓ Email sent successfully! Message ID: {result['id']}")
        
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
        
        # Save draft ID for easy reference
        save_draft_id(draft_id, subject, ', '.join(to))
        
        click.echo(f"✓ Draft created successfully!")
        click.echo(f"  Draft ID: {draft_id}")
        click.echo(f"  Subject: {subject}")
        click.echo(f"  To: {', '.join(to)}")
        click.echo(f"\nYou can send this draft using: gmail-cli send-draft --id {draft_id}")
        
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Unexpected error: {e}")


@cli.command('list-drafts')
@click.option('--max-results', default=10, help='Maximum number of drafts to list')
@add_config_options
def list_drafts(max_results, credentials_file, token_file, client_id, client_secret, config_file):
    """List existing email drafts."""
    
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
        
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Configuration error: {e}")
    
    try:
        # Authenticate and build service
        click.echo("\nAuthenticating with Gmail...")
        creds = authenticate_gmail(config)
        service = build('gmail', 'v1', credentials=creds)
        
        # List drafts
        click.echo(f"Fetching up to {max_results} drafts...\n")
        drafts = list_user_drafts(service, 'me', max_results)
        
        if not drafts:
            click.echo("No drafts found.")
            return
        
        # Load saved draft IDs
        saved_drafts = load_draft_ids()
        
        click.echo(f"Found {len(drafts)} draft(s):\n")
        for draft in drafts:
            click.echo(f"ID: {draft['id']}")
            click.echo(f"  Subject: {draft['subject']}")
            click.echo(f"  To: {draft['to']}")
            if draft['date']:
                click.echo(f"  Date: {draft['date']}")
            if draft['id'] in saved_drafts:
                click.echo(f"  (Saved locally)")
            click.echo()
        
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Unexpected error: {e}")


@cli.command('send-draft')
@click.option('--id', 'draft_id', required=True, help='Draft ID to send')
@add_config_options
def send_draft(draft_id, credentials_file, token_file, client_id, client_secret, config_file):
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
        result = send_draft_message(service, 'me', draft_id)
        
        # Remove from local storage
        remove_draft_id(draft_id)
        
        click.echo(f"✓ Draft sent successfully! Message ID: {result['id']}")
        
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Unexpected error: {e}")


@cli.command('update-draft')
@click.option('--id', 'draft_id', required=True, help='Draft ID to update')
@click.option('--to', multiple=True, help='New recipient email addresses')
@click.option('--subject', help='New email subject')
@click.option('--body', help='New email body text')
@click.option('--body-file', type=click.Path(exists=True), 
              help='Read new email body from file')
@click.option('--input-format', type=click.Choice(['markdown', 'html', 'plaintext']), 
              default='markdown', help='Input format for email body (default: markdown)')
@click.option('--cc', multiple=True, help='New CC email addresses')
@click.option('--bcc', multiple=True, help='New BCC email addresses')
@click.option('--attachment', multiple=True, type=click.Path(exists=True),
              help='New file paths to attach')
@click.option('--signature/--no-signature', default=True, 
              help='Include Gmail default signature (default: enabled)')
@add_config_options
def update_draft_cmd(draft_id, to, subject, body, body_file, input_format, cc, bcc, attachment, signature,
                     credentials_file, token_file, client_id, client_secret, config_file):
    """Update an existing draft."""
    
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
        
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Configuration error: {e}")
    
    # At least one update field must be provided
    if not any([to, subject, body, body_file, cc, bcc, attachment]):
        raise click.ClickException("At least one field to update must be provided")
    
    if body and body_file:
        raise click.ClickException("Cannot specify both --body and --body-file")
    
    try:
        # Authenticate and build service
        click.echo("\nAuthenticating with Gmail...")
        creds = authenticate_gmail(config)
        service = build('gmail', 'v1', credentials=creds)
        
        # Get current draft to preserve fields not being updated
        click.echo(f"Fetching draft {draft_id}...")
        current_draft = service.users().drafts().get(
            userId='me',
            id=draft_id
        ).execute()
        
        # Extract current headers
        headers = {h['name']: h['value'] 
                  for h in current_draft['message']['payload'].get('headers', [])}
        
        # Use current values as defaults
        if not to:
            to_str = headers.get('To', '')
            to = tuple(addr.strip() for addr in to_str.split(',')) if to_str else ()
        if not subject:
            subject = headers.get('Subject', '')
        if not cc:
            cc_str = headers.get('Cc', '')
            cc = tuple(addr.strip() for addr in cc_str.split(',')) if cc_str else ()
        if not bcc:
            bcc_str = headers.get('Bcc', '')
            bcc = tuple(addr.strip() for addr in bcc_str.split(',')) if bcc_str else ()
        
        # If no new body provided, we need to get the current body
        # This is complex with Gmail API, so for now require body for updates
        if not body and not body_file:
            raise click.ClickException(
                "Body update is required when updating a draft. "
                "Gmail API does not easily expose draft body for modification."
            )
        
        # Read body from file if specified
        if body_file:
            try:
                with open(body_file, 'r', encoding='utf-8') as f:
                    body = f.read()
            except Exception as e:
                raise click.ClickException(f"Error reading body file: {e}")
        
        # Get sender
        sender = get_sender_email(service)
        click.echo(f"Updating draft from: {sender}")
        
        # Convert body to HTML
        click.echo(f"Converting {input_format} content to HTML...")
        body_html = convert_to_html(body, input_format)
        
        # Get Gmail signature if requested
        gmail_signature = ''
        if signature:
            click.echo("Retrieving Gmail signature...")
            gmail_signature = get_gmail_signature(service)
        
        # Create new message
        if attachment:
            click.echo(f"Creating updated message with {len(attachment)} attachment(s)...")
            message = create_message_with_attachment(
                sender, list(to), subject, body_html, 
                list(cc) if cc else None, 
                list(bcc) if bcc else None, 
                list(attachment),
                gmail_signature
            )
        else:
            click.echo("Creating updated message...")
            message = create_message(
                sender, list(to), subject, body_html,
                list(cc) if cc else None,
                list(bcc) if bcc else None,
                gmail_signature
            )
        
        # Update draft
        click.echo("Updating draft...")
        updated_draft = update_draft(service, 'me', draft_id, message)
        
        click.echo(f"✓ Draft updated successfully!")
        click.echo(f"  Draft ID: {draft_id}")
        click.echo(f"  Subject: {subject}")
        click.echo(f"  To: {', '.join(to)}")
        
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Unexpected error: {e}")


if __name__ == '__main__':
    cli()
