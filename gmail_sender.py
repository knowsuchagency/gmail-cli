# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "google-api-python-client",
#     "google-auth",
#     "google-auth-oauthlib",
#     "google-auth-httplib2",
#     "click",
#     "markdown",
# ]
# ///

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

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Gmail API scopes for sending emails, reading profile, and settings
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.settings.basic'
]
CREDENTIALS_FILE = '/Users/stephanfitzpatrick/Downloads/OAuth Client ID Secret (1).json'
TOKEN_FILE = 'gmail_token.json'


def authenticate_gmail():
    """Authenticate with Gmail API using OAuth2 flow."""
    creds = None
    
    # Load existing token if available
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
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
            if not os.path.exists(CREDENTIALS_FILE):
                raise click.ClickException(
                    f"Credentials file not found at {CREDENTIALS_FILE}. "
                    "Please ensure you have downloaded the OAuth client credentials from Google Cloud Console."
                )
            
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
                click.echo("Authentication successful!")
            except Exception as e:
                raise click.ClickException(f"Authentication failed: {e}")
        
        # Save the credentials for the next run
        try:
            with open(TOKEN_FILE, 'w') as token:
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
    """Convert content to HTML based on input format."""
    if input_format == 'html':
        return content
    elif input_format == 'markdown':
        return markdown.markdown(content)
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


@click.command()
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
def send_email(to, subject, body, body_file, input_format, cc, bcc, attachment, sender, signature):
    """Send an email via Gmail API."""
    
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
        creds = authenticate_gmail()
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


if __name__ == '__main__':
    send_email()
