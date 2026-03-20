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

## Structured SFT Pipeline

The fine-tuning flow is built around supervised examples of topic to comment, not raw post continuation.

1. Build the structured dataset:

```bash
./phase1_prepare_raw_data.py
```

Inspect noisy topic candidates before training:

```bash
./phase1_audit_training_data.py
```

This generates [prepared/fefe_training_data.json](prepared/fefe_training_data.json) with rows shaped like:

```json
{
	"topic": "Innenministerium plant neue Chatkontrolle",
	"context": "Diskutiert wird eine Ausweitung automatisierter Überwachung privater Kommunikation.",
	"url": "https://example.invalid/story",
	"target_comment": "[l] ..."
}
```

2. Fine-tune the LoRA adapter:

```bash
./phase2_training.py
```

Training converts each row into one fixed prompt structure and feeds it through the Llama 3 chat template:

```text
### Instruction
Write a short German blog comment in a dry, ironic, satirical tone.

### Input
Topic: <TOPIC>
Context: <OPTIONAL CONTEXT>
URL: <OPTIONAL URL>

### Response
```

3. Run inference with the exact same structure:

```bash
./phase3_inference.py
```

If [fefe-lora-llama3](fefe-lora-llama3) exists, inference loads the trained LoRA adapter on top of the base model.