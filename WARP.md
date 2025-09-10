# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

Gmail CLI Sender is a Python command-line tool for sending emails via Gmail API using OAuth2 authentication. It's a single-script application that uses `pyproject.toml` for dependency management with uv, allowing it to run directly with `uv run` after syncing dependencies.

## Architecture

- **Single-file design**: All functionality is contained in `gmail_sender.py`
- **pyproject.toml dependency management**: Dependencies are declared in `pyproject.toml` and managed with uv
- **OAuth2 flow**: Uses Google's OAuth2 with local server callback for authentication
- **Multi-format support**: Converts Markdown (default), HTML, and plaintext to HTML emails
- **Gmail API integration**: Leverages Gmail API v1 for sending emails and retrieving signatures

### Key Components

- **Authentication layer** (`authenticate_gmail()`): Handles OAuth2 flow, token refresh, and persistence
- **Content conversion** (`convert_to_html()`): Transforms input formats to HTML with enhanced styling
- **Message creation** (`create_message()`, `create_message_with_attachment()`): Builds MIME messages
- **Gmail integration** (`get_gmail_signature()`, `send_message()`): Interacts with Gmail API

## Common Development Commands

### Running the Tool
```bash
# Basic email sending (uses Markdown by default)
uv run gmail_sender.py --to recipient@example.com --subject "Test" --body "**Bold** text"

# Send from file
uv run gmail_sender.py --to user@example.com --subject "Report" --body-file report.md

# Send HTML email
uv run gmail_sender.py --to user@example.com --subject "Newsletter" --body-file newsletter.html --input-format html

# Send with attachments and multiple recipients
uv run gmail_sender.py --to user1@example.com --to user2@example.com --cc manager@example.com --subject "Files" --body "See attached" --attachment file1.pdf --attachment file2.txt
```

### Testing Different Input Formats
```bash
# Test Markdown conversion (includes syntax highlighting and tables)
uv run gmail_sender.py --to test@example.com --subject "Markdown Test" --body-file test_markdown.md

# Test code formatting
uv run gmail_sender.py --to test@example.com --subject "Code Test" --body-file code_test.md

# Test plain text conversion
uv run gmail_sender.py --to test@example.com --subject "Plain Text" --body "Simple text" --input-format plaintext
```

### Development and Debugging
```bash
# Install/sync dependencies
uv sync

# Check dependencies
cat pyproject.toml

# Validate OAuth credentials setup
ls -la /Users/stephanfitzpatrick/Downloads/OAuth\ Client\ ID\ Secret\ \(1\).json

# Check if authentication token exists
ls -la gmail_token.json

# Check virtual environment
ls -la .venv/
```

## Configuration Requirements

### OAuth2 Setup
1. Download OAuth2 credentials from Google Cloud Console
2. Place credentials at: `/Users/stephanfitzpatrick/Downloads/OAuth Client ID Secret (1).json`
3. First run will trigger OAuth flow and create `gmail_token.json` locally

### Gmail API Permissions Required
- `gmail.send` - Send emails
- `gmail.readonly` - Read user profile  
- `gmail.settings.basic` - Retrieve signatures

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
├── gmail_sender.py          # Main application
├── pyproject.toml          # Project configuration and dependencies
├── uv.lock                 # Dependency lock file (auto-generated)
├── .venv/                  # Virtual environment (auto-generated)
├── README.md               # Usage documentation
├── gmail_token.json        # OAuth2 token (auto-generated, gitignored)
├── test_markdown.md        # Markdown test file
├── code_test.md           # Code formatting test file
└── .gitignore             # Excludes tokens and Python artifacts
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

# Run the tool (uv will automatically use the .venv)
uv run gmail_sender.py --help
```
