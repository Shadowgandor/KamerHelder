# macOS Setup Guide for Tweede Kamer Project

## Step 1: Install Python (if not already installed)

macOS comes with Python, but it's usually an older version. Let's install a modern version:

### Option A: Using Homebrew (Recommended)
```bash
# First, install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Then install Python
brew install python
```

### Option B: Download from Python.org
1. Go to https://www.python.org/downloads/
2. Download the latest Python 3.x version for macOS
3. Run the installer

## Step 2: Verify Python Installation

Open Terminal (Applications → Utilities → Terminal) and check:

```bash
# Check Python version (should be 3.8 or higher)
python3 --version

# Check pip (Python package manager)
pip3 --version
```

## Step 3: Create Project Directory

```bash
# Create a new folder for your project
mkdir ~/tweede-kamer-project
cd ~/tweede-kamer-project
```

## Step 4: Set Up Virtual Environment (Recommended)

This keeps your project dependencies separate from other Python projects:

```bash
# Create virtual environment
python3 -m venv venv

# Activate it (you'll need to do this every time you work on the project)
source venv/bin/activate

# Your terminal prompt should now show (venv) at the beginning
```

## Step 5: Install Required Packages

```bash
# Install the packages we need
pip install tkapi requests
```

## Step 6: Create the Python Script

Create a new file called `tk_data_retriever.py`:

```bash
# Create the file
touch tk_data_retriever.py

# Open it in a text editor (choose one):
open -a TextEdit tk_data_retriever.py
# OR if you have VS Code:
code tk_data_retriever.py
# OR if you have another editor like nano:
nano tk_data_retriever.py
```

Copy and paste the Python code from the artifact into this file and save it.

## Step 7: Run the Script

```bash
# Make sure you're in the project directory and virtual environment is active
python tk_data_retriever.py
```

## Step 8: View the Results

After the script runs, you'll have several new files:

```bash
# List the files that were created
ls -la

# View the JSON files (choose one method):
cat recent_verslagen.json
# OR open in a text editor:
open -a TextEdit recent_verslagen.json
# OR use a JSON viewer online by copying the content
```

## Daily Workflow

Every time you want to work on this project:

1. Open Terminal
2. Navigate to your project:
   ```bash
   cd ~/tweede-kamer-project
   ```
3. Activate virtual environment:
   ```bash
   source venv/bin/activate
   ```
4. Run your script or work on new code:
   ```bash
   python tk_data_retriever.py
   ```

## Troubleshooting

### If you get "command not found" errors:
- Try using `python3` instead of `python`
- Try using `pip3` instead of `pip`

### If you get permission errors:
```bash
# Add --user flag to pip install
pip install --user tkapi requests
```

### If the script fails with import errors:
```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Reinstall packages
pip install tkapi requests
```

### If you want to deactivate the virtual environment:
```bash
deactivate
```

## Useful Commands

```bash
# See what packages are installed
pip list

# Update a package
pip install --upgrade tkapi

# See detailed information about the project directory
ls -la

# Check if virtual environment is active
which python
# Should show something like: /Users/yourname/tweede-kamer-project/venv/bin/python
```

## Recommended Text Editors for Code

- **VS Code** (free, very popular): https://code.visualstudio.com/
- **Sublime Text** (free trial): https://www.sublimetext.com/
- **TextEdit** (comes with macOS, but basic)
- **nano** (terminal-based, comes with macOS)

## Next Steps

Once you have the basic script working:
1. Explore the generated JSON files to understand the data structure
2. We can add text extraction from PDF/Word documents  
3. Set up database storage
4. Integrate with an LLM for summarization
5. Build a simple web interface

## File Structure You'll Have

```
~/tweede-kamer-project/
├── venv/                     # Virtual environment (don't edit this)
├── tk_data_retriever.py      # Your main script
├── recent_vergaderingen.json # Meeting data
├── recent_verslagen.json     # All meeting reports
├── plenaire_verslagen.json   # Just plenary reports
└── documents/                # Downloaded PDF/Word files
    └── [various document files]
```
