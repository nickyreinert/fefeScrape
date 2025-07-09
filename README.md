# fefeScrape
Parse fefes blog to count words, message and used sources (links to external pages)

This is a Python script that scrapes all content from blog.fefe.de to count words, messages and links to external sources. 

It provides following parameters:

-h, --help print help / available parameters
-s, --start start date, expected format is YYYY-MM, e.g. 2010-05
-i, --input file name template, when looping through date range, date will be prepended as 201005
-o, --output file name template, same as input
-l, --limit limit loop to this integer (default: 240 months)
-v, --verbose verbose output, will print more information to console
--parse-source parse external links to extract meta data like titles from linked sources

If you provide output file name, the script will parse the remote location and put all content as HTML into the given output files. One file will be created for each months. If you want to reparse the files, you can provide the same template file name to the parameter input (not output). 

The script generates CSV and JSON files with the extracted data:
- `messages.json` / `messages.csv` - All messages with metadata, content, and external source information
- `words.json` / `words.csv` - Word frequency analysis by month and total
- `domains.json` / `domains.csv` - Domain/source frequency analysis

## Usage Examples

```bash
# Parse from March 2005 with verbose output
python fefe.py --start 2005-03 --verbose

# Parse from local files with source parsing
python fefe.py --input data.html --start 2005-03 --parse-source --verbose

# Save raw HTML files and parse external sources
python fefe.py --start 2005-03 --output _raw.html --parse-source --limit 12
``` 

# Preparation

1. create virtual environment
```python
python3 -m venv ./.venv
```

2. load virtual environment

```python
source .venv/bin/activate
```

3. install packages

```python
pip3 install -r requirements.txt 
```