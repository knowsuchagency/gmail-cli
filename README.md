# Gmail CLI

A command-line tool for sending emails and managing drafts via Gmail API using OAuth2 authentication.

## Features

- **Email drafts** - Create, list, update, and send email drafts
- **Direct sending** - Send emails immediately or from existing drafts
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

### Sending Emails

```bash
# Send email directly with Markdown content (default)
gmail-cli send --to recipient@example.com --subject "Hello" --body "**Bold** and *italic* text"

# Send from markdown file
gmail-cli send --to user@example.com --subject "Report" --body-file report.md

# Send HTML email
gmail-cli send --to user@example.com --subject "Newsletter" --body-file newsletter.html --input-format html

# Send with attachments
gmail-cli send --to user@example.com --subject "Files" --body "See attached" --attachment file1.pdf --attachment file2.txt

# Multiple recipients
gmail-cli send --to user1@example.com --to user2@example.com --cc manager@example.com --subject "Meeting" --body "Agenda attached"
```

### Working with Drafts

```bash
# Create a draft
gmail-cli draft --to recipient@example.com --subject "Draft Email" --body "This is a draft"
# Returns: Draft ID: r-123456789

# List all drafts
gmail-cli list-drafts
# Shows draft IDs, subjects, and recipients

# Update an existing draft
gmail-cli update-draft --id r-123456789 --body "Updated content" --subject "New Subject"

# Send a draft
gmail-cli send-draft --id r-123456789

# Send existing draft using send command
gmail-cli send --draft-id r-123456789
```

### Draft Workflow Example

```bash
# 1. Create a draft with initial content
gmail-cli draft --to team@example.com --subject "Project Update" --body-file update.md --attachment report.pdf

# 2. Review drafts
gmail-cli list-drafts

# 3. Update the draft if needed
gmail-cli update-draft --id r-123456789 --body "Revised update content"

# 4. Send when ready
gmail-cli send-draft --id r-123456789
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

### Common Options (All Commands)
- `--credentials-file` - Path to OAuth2 credentials JSON file
- `--token-file` - Path to store/read OAuth2 token
- `--client-id` - OAuth2 client ID
- `--client-secret` - OAuth2 client secret
- `--config-file` - Path to configuration JSON file

### Send Command Options
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
- `--draft-id` - Send an existing draft instead of creating new email

### Draft Command Options
Same as send command options (except `--draft-id`)

### List-Drafts Command Options
- `--max-results` - Maximum number of drafts to list (default: 10)

### Update-Draft Command Options
- `--id` - Draft ID to update (required)
- All other options from send command (optional, for updating specific fields)

### Send-Draft Command Options
- `--id` - Draft ID to send (required)

## Dependencies

All dependencies are managed via PEP 723 inline metadata:
- google-api-python-client
- google-auth
- google-auth-oauthlib  
- google-auth-httplib2
- click
- markdown
- Pygments (for syntax highlighting in code blocks)
