# Gmail CLI

A command-line tool for sending emails and managing drafts via Gmail API using OAuth2 authentication.

## Features

- **Two-step workflow** - Create a draft, then send it
- **OAuth2 authentication** - Secure Gmail API access
- **Multiple input formats** - Markdown (default), HTML, and plain text
- **Automatic signature inclusion** - Uses your Gmail signature by default
- **File attachments** - Support for multiple attachments
- **Multiple recipients** - TO, CC, and BCC support
- **Configurable credentials** - Support for client ID/secret or credentials file

## Installation

```bash
# Install using pip
pip install gmail-cli

# Or using uv
uv add gmail-cli
```

## Usage

### Two-Step Email Workflow

The Gmail CLI follows a simple two-step process:
1. **Create a draft** with all your email content
2. **Send the draft** using its ID

### Step 1: Creating Drafts

```bash
# Create draft with Markdown content (default)
gmail-cli draft --to recipient@example.com --subject "Hello" --body "**Bold** and *italic* text"
# Returns: Draft ID: r-123456789

# Create draft from markdown file
gmail-cli draft --to user@example.com --subject "Report" --body-file report.md

# Create HTML email draft
gmail-cli draft --to user@example.com --subject "Newsletter" --body-file newsletter.html --input-format html

# Create draft with attachments
gmail-cli draft --to user@example.com --subject "Files" --body "See attached" --attachment file1.pdf --attachment file2.txt

# Multiple recipients
gmail-cli draft --to user1@example.com --to user2@example.com --cc manager@example.com --subject "Meeting" --body "Agenda attached"
```

### Step 2: Sending Drafts

```bash
# Send a draft using its ID
gmail-cli send --draft-id r-123456789
```

### Complete Workflow Example

```bash
# 1. Create a draft with your content
gmail-cli draft --to team@example.com --subject "Project Update" --body-file update.md --attachment report.pdf
# Output: Draft created! Draft ID: r-123456789

# 2. Send the draft when ready
gmail-cli send --draft-id r-123456789
# Output: Draft sent successfully!
```

## Setup

### Authentication Configuration

The CLI supports multiple authentication methods:

#### Option 1: Credentials File (Legacy)
1. Download OAuth2 credentials from Google Cloud Console
2. Use `--credentials-file path/to/credentials.json` when running commands

#### Option 2: Client ID and Secret (Recommended)
1. Get your OAuth2 client ID and secret from Google Cloud Console
2. Configure using either:
   - CLI arguments: `--client-id YOUR_ID --client-secret YOUR_SECRET`
   - Config file: Create `~/.config/gmail-cli/config.json`:
     ```json
     {
       "client_id": "YOUR_CLIENT_ID",
       "client_secret": "YOUR_CLIENT_SECRET"
     }
     ```

### First Run
On first use, the tool will open a browser for OAuth2 authentication and save the token for future use.

## Command Options

### Common Options (Both Commands)
- `--credentials-file` - Path to OAuth2 credentials JSON file
- `--token-file` - Path to store/read OAuth2 token
- `--client-id` - OAuth2 client ID
- `--client-secret` - OAuth2 client secret
- `--config-file` - Path to configuration JSON file

### Draft Command Options
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

### Send Command Options
- `--draft-id` - Draft ID to send (required)

## Dependencies

All dependencies are managed via PEP 723 inline metadata:
- google-api-python-client
- google-auth
- google-auth-oauthlib  
- google-auth-httplib2
- click
- markdown
- Pygments (for syntax highlighting in code blocks)
