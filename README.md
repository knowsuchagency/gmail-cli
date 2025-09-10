# Gmail CLI Sender

A command-line tool for sending emails via Gmail API using OAuth2 authentication.

## Features

- **PEP 723 inline metadata** - Run directly with `uv run gmail_sender.py`
- **OAuth2 authentication** - Secure Gmail API access
- **Multiple input formats** - Markdown (default), HTML, and plain text
- **Automatic signature inclusion** - Uses your Gmail signature by default
- **File attachments** - Support for multiple attachments
- **Multiple recipients** - TO, CC, and BCC support

## Usage

```bash
# Send email with Markdown content (default)
uv run gmail_sender.py --to recipient@example.com --subject "Hello" --body "**Bold** and *italic* text"

# Send from markdown file
uv run gmail_sender.py --to user@example.com --subject "Report" --body-file report.md

# Send HTML email
uv run gmail_sender.py --to user@example.com --subject "Newsletter" --body-file newsletter.html --input-format html

# Send with attachments
uv run gmail_sender.py --to user@example.com --subject "Files" --body "See attached" --attachment file1.pdf --attachment file2.txt

# Multiple recipients
uv run gmail_sender.py --to user1@example.com --to user2@example.com --cc manager@example.com --subject "Meeting" --body "Agenda attached"
```

## Setup

1. Download OAuth2 credentials from Google Cloud Console
2. Place credentials file at `/Users/stephanfitzpatrick/Downloads/OAuth Client ID Secret (1).json`
3. Run the script - it will guide you through the OAuth flow on first use

## Options

- `--to` - Recipient email addresses (required, multiple allowed)
- `--subject` - Email subject (required)
- `--body` - Email body text
- `--body-file` - Read body content from file
- `--input-format` - Input format: `markdown` (default), `html`, or `plaintext`
- `--cc` - CC recipients (multiple allowed)
- `--bcc` - BCC recipients (multiple allowed)
- `--attachment` - File attachments (multiple allowed)
- `--sender` - Override sender email (if permitted)
- `--signature/--no-signature` - Include Gmail signature (default: enabled)

## Dependencies

All dependencies are managed via PEP 723 inline metadata:
- google-api-python-client
- google-auth
- google-auth-oauthlib  
- google-auth-httplib2
- click
- markdown
