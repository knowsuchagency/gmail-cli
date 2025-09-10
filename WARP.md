# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

Gmail CLI is a Python command-line tool for sending emails and managing drafts via Gmail API using OAuth2 authentication. It's a single-script application with multiple subcommands that uses `pyproject.toml` for dependency management with uv.

## Architecture

- **Single-file design**: All functionality is contained in `gmail_sender.py`
- **Multi-command CLI**: Uses Click subcommands for send, draft, list-drafts, update-draft, and send-draft operations
- **pyproject.toml dependency management**: Dependencies are declared in `pyproject.toml` and managed with uv
- **OAuth2 flow**: Uses Google's OAuth2 with local server callback for authentication
- **Multi-format support**: Converts Markdown (default), HTML, and plaintext to HTML emails
- **Gmail API integration**: Leverages Gmail API v1 for sending emails, managing drafts, and retrieving signatures
- **Draft management**: Create, list, update, and send email drafts with local ID storage

### Key Components

- **Configuration management** (`GmailConfig`): Handles credentials, client ID/secret, and config files
- **Authentication layer** (`authenticate_gmail()`): Handles OAuth2 flow, token refresh, and persistence
- **Content conversion** (`convert_to_html()`): Transforms input formats to HTML with enhanced styling
- **Message creation** (`create_message()`, `create_message_with_attachment()`): Builds MIME messages
- **Draft operations** (`create_draft()`, `list_user_drafts()`, `update_draft()`, `send_draft_message()`): Draft management
- **Gmail integration** (`get_gmail_signature()`, `send_message()`): Interacts with Gmail API
- **CLI commands** (`cli`, `send`, `draft`, `list_drafts`, `send_draft`, `update_draft_cmd`): Click-based subcommands

## Common Development Commands

### Sending Emails
```bash
# Basic email sending (uses Markdown by default)
gmail-cli send --to recipient@example.com --subject "Test" --body "**Bold** text"

# Send from file
gmail-cli send --to user@example.com --subject "Report" --body-file report.md

# Send HTML email
gmail-cli send --to user@example.com --subject "Newsletter" --body-file newsletter.html --input-format html

# Send with attachments and multiple recipients
gmail-cli send --to user1@example.com --to user2@example.com --cc manager@example.com --subject "Files" --body "See attached" --attachment file1.pdf --attachment file2.txt
```

### Managing Drafts
```bash
# Create a draft
gmail-cli draft --to recipient@example.com --subject "Draft" --body "Draft content"

# List drafts
gmail-cli list-drafts --max-results 20

# Update a draft
gmail-cli update-draft --id r-123456789 --body "New content" --subject "Updated"

# Send a draft
gmail-cli send-draft --id r-123456789

# Send existing draft via send command
gmail-cli send --draft-id r-123456789
```

### Testing Different Input Formats
```bash
# Test Markdown conversion (includes syntax highlighting and tables)
gmail-cli send --to test@example.com --subject "Markdown Test" --body-file test_markdown.md

# Test code formatting
gmail-cli send --to test@example.com --subject "Code Test" --body-file code_test.md

# Test plain text conversion
gmail-cli send --to test@example.com --subject "Plain Text" --body "Simple text" --input-format plaintext

# Test draft with markdown
gmail-cli draft --to test@example.com --subject "Draft Test" --body "# Markdown Draft\n\n**Bold** and *italic*"
```

### Development and Debugging
```bash
# Install/sync dependencies
uv sync

# Check dependencies
cat pyproject.toml

# Check authentication configuration
ls -la ~/.config/gmail-cli/

# Check if authentication token exists
ls -la ~/.config/gmail-cli/token.json

# Check draft storage
cat ~/.config/gmail-cli/drafts.json

# Check virtual environment
ls -la .venv/

# Run with verbose authentication
gmail-cli send --help  # Shows all configuration options
```

## Configuration Requirements

### OAuth2 Setup
The CLI supports multiple authentication methods:

#### Option 1: Client ID and Secret (Recommended)
1. Get OAuth2 client ID and secret from Google Cloud Console
2. Configure using:
   - CLI arguments: `--client-id YOUR_ID --client-secret YOUR_SECRET`
   - Config file: `~/.config/gmail-cli/config.json`:
     ```json
     {
       "client_id": "YOUR_CLIENT_ID",
       "client_secret": "YOUR_CLIENT_SECRET"
     }
     ```

#### Option 2: Credentials File
1. Download OAuth2 credentials from Google Cloud Console
2. Use `--credentials-file path/to/credentials.json` when running commands

3. First run will trigger OAuth flow and save token to `~/.config/gmail-cli/token.json`

### Gmail API Permissions Required
- `gmail.send` - Send emails
- `gmail.readonly` - Read user profile and drafts
- `gmail.settings.basic` - Retrieve signatures
- `gmail.compose` - Create and update drafts
- `gmail.modify` - Manage drafts

## Technical Details

### Markdown Processing
- Uses `markdown` library with extensions: `codehilite`, `fenced_code`, `tables`, `toc`, `nl2br`
- Includes custom CSS for email-compatible code highlighting using Pygments
- Syntax highlighting with GitHub-style formatting (inline styles for email compatibility)

### Email Format Handling
- All emails are sent as HTML regardless of input format
- Plaintext is converted to HTML with proper escaping and line break handling
- HTML content is passed through unchanged
- Markdown gets full processing with syntax highlighting and table support

### Signature Integration
- Automatically retrieves user's Gmail signature from primary send-as address
- Signatures are appended as HTML to the email body
- Warning system for plaintext + signature combinations (HTML signatures converted to text)

### Error Handling
- OAuth2 token refresh with fallback to re-authentication
- Gmail API quota and permission error handling
- File attachment validation and MIME type detection
- Graceful degradation for signature retrieval failures

## File Structure
```
gmail-cli/
├── gmail_sender.py          # Main application with CLI commands
├── pyproject.toml          # Project configuration and dependencies
├── uv.lock                 # Dependency lock file (auto-generated)
├── .venv/                  # Virtual environment (auto-generated)
├── README.md               # Usage documentation
├── WARP.md                 # This file - development guidance
├── test_markdown.md        # Markdown test file
├── code_test.md           # Code formatting test file
├── .gitignore             # Excludes tokens and Python artifacts
└── ~/.config/gmail-cli/    # Configuration directory (user home)
    ├── config.json         # Optional client ID/secret configuration
    ├── token.json          # OAuth2 token (auto-generated)
    └── drafts.json         # Local draft ID storage
```

## Dependencies Management
Dependencies are managed via `pyproject.toml` and installed with `uv sync`:
- google-api-python-client
- google-auth, google-auth-oauthlib, google-auth-httplib2
- click (CLI interface)
- markdown (content conversion)
- Pygments (syntax highlighting)

### Initial Setup
```bash
# Install dependencies and create virtual environment
uv sync

# Install the CLI tool
uv pip install -e .

# Run the tool
gmail-cli --help

# Or run directly without installation
uv run gmail-cli --help
```

## Command Reference

### Main Commands
- `gmail-cli send` - Send an email or existing draft
- `gmail-cli draft` - Create a new draft
- `gmail-cli list-drafts` - List all drafts
- `gmail-cli send-draft` - Send a specific draft
- `gmail-cli update-draft` - Update an existing draft

### Common Workflows

#### Quick Send
```bash
gmail-cli send --to user@example.com --subject "Quick message" --body "Hello!"
```

#### Draft Workflow
```bash
# Create draft
gmail-cli draft --to team@example.com --subject "Proposal" --body-file proposal.md

# Review and edit in Gmail UI or update via CLI
gmail-cli update-draft --id r-123456789 --body-file revised_proposal.md

# Send when ready
gmail-cli send-draft --id r-123456789
```
