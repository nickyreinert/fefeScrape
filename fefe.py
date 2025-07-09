#!./.venv/bin/python3
import urllib.request
import ssl
from datetime import datetime
from dateutil.relativedelta import *
import argparse
from bs4 import BeautifulSoup # xml/html parser
import re # regular expresions
import json # to convert python's dictionary to json
import sys, getopt # to get parameters from command line
import signal
import select
import termios
import tty

# Global flag for interrupt handling
interrupt_requested = False

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    global interrupt_requested
    interrupt_requested = True
    print("\n\nInterrupt received! Finishing current message and saving data...")

def check_for_escape():
    """Check if ESC key was pressed (non-blocking)"""
    global interrupt_requested
    
    # Simple fallback: just return if already interrupted
    if interrupt_requested:
        return True
    
    # Only check on Unix-like systems (macOS, Linux)
    if sys.platform not in ['darwin', 'linux', 'linux2']:
        return False
        
    try:
        # Check if input is available
        if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
            # Save terminal settings
            old_settings = termios.tcgetattr(sys.stdin)
            try:
                # Set terminal to raw mode
                tty.setraw(sys.stdin.fileno())
                # Read one character
                char = sys.stdin.read(1)
                # Check if it's ESC (ASCII 27)
                if ord(char) == 27:
                    interrupt_requested = True
                    print("\n\nESC pressed! Finishing current message and saving data...")
                    return True
            finally:
                # Restore terminal settings
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
    except Exception as e:
        # If there's any error with terminal handling, just continue silently
        # This handles cases where terminal manipulation is not available
        pass
    
    return False

# thanks to https://www.netaction.de/datenvisualisierung-von-fefes-blogzeiten/ for figuring this out
timestampKey    = 0xFEFEC0DE

# fefe provides monthly overviews, containing all articles for one month, expected date-format is Ym (201505 for May, 2015)
urlTemplate     = "https://blog.fefe.de/?mon="

# prevent loop to run infinitely, for backup, script stops afert iMax iterations
iMax            = 240

# what chars to strip from words, before consider them
ignoreChars     = '()[],;.:\!?"„\''
# using regex for a more cleaner result, ignore the prior line, see description below
ignoreCharsRegEx = '[\W\_]' # \W would not work, because _ is being ignored
# for this word cloud, ignore words with less then minWordLength characters 
minWordLength   = 4
# heads up: as we also strip special chars (,.;) this will also ignore smilies... we dont count, how much Fefe uses smilies.


def log(message, indent=0, verbose=False):
    if not verbose:
        return
    if indent > 0:
        print(' ' * indent, end='')
    print(message)

def parseExternalSource(url, verbose):
    """
    Parse external URL to extract meta data like title, description, etc.
    Returns a dictionary with extracted meta data.
    """
    log(f"Parsing external source: {url}", 18, verbose)
    
    try:
        # Create SSL context for potentially problematic certificates
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Add headers to mimic a real browser
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Fetch the page with timeout
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as response:
            if response.getcode() != 200:
                log(f"HTTP {response.getcode()} for {url}", 20, verbose)
                return None
                
            html = response.read().decode('utf-8', errors='ignore')
            
        # Parse HTML to extract meta data
        soup = BeautifulSoup(html, features="html.parser")
        
        metadata = {
            'title': None,
            'description': None,
            'author': None,
            'published': None,
            'site_name': None,
            'url': url
        }
        
        # Try to get title from various sources
        title_sources = [
            soup.find('meta', {'property': 'og:title'}),
            soup.find('meta', {'name': 'twitter:title'}),
            soup.find('title'),
            soup.find('h1')
        ]
        
        for source in title_sources:
            if source:
                if source.name == 'meta':
                    metadata['title'] = source.get('content', '').strip()
                else:
                    metadata['title'] = source.get_text().strip()
                if metadata['title']:
                    break
        
        # Try to get description
        desc_sources = [
            soup.find('meta', {'property': 'og:description'}),
            soup.find('meta', {'name': 'twitter:description'}),
            soup.find('meta', {'name': 'description'})
        ]
        
        for source in desc_sources:
            if source:
                metadata['description'] = source.get('content', '').strip()
                if metadata['description']:
                    break
        
        # Try to get author
        author_sources = [
            soup.find('meta', {'name': 'author'}),
            soup.find('meta', {'property': 'article:author'}),
            soup.find('meta', {'name': 'twitter:creator'})
        ]
        
        for source in author_sources:
            if source:
                metadata['author'] = source.get('content', '').strip()
                if metadata['author']:
                    break
        
        # Try to get published date
        date_sources = [
            soup.find('meta', {'property': 'article:published_time'}),
            soup.find('meta', {'name': 'date'}),
            soup.find('time')
        ]
        
        for source in date_sources:
            if source:
                if source.name == 'meta':
                    metadata['published'] = source.get('content', '').strip()
                else:
                    metadata['published'] = source.get('datetime', source.get_text()).strip()
                if metadata['published']:
                    break
        
        # Try to get site name
        site_sources = [
            soup.find('meta', {'property': 'og:site_name'}),
            soup.find('meta', {'name': 'application-name'})
        ]
        
        for source in site_sources:
            if source:
                metadata['site_name'] = source.get('content', '').strip()
                if metadata['site_name']:
                    break
        
        log(f"Extracted metadata: title='{metadata['title']}', site='{metadata['site_name']}'", 20, verbose)
        return metadata
        
    except Exception as e:
        log(f"Error parsing {url}: {str(e)}", 20, verbose)
        return None

def isMonthAlreadyProcessed(month, verbose):
    """
    Check if a month has already been processed by looking for existing HTML output file.
    Returns True if the month should be skipped, False otherwise.
    """
    import os
    
    # Check if HTML output file exists for this month
    html_filename = f"{month}data.html"
    if os.path.exists(html_filename):
        log(f"Found existing HTML file for month {month}: {html_filename}", 6, verbose)
        return True
    
    log(f"No existing HTML file found for month {month}", 6, verbose)
    return False

def getMessages(startDate, inputFile, outputFile, iMax, verbose, parseSource, force):

    log("Starting message parsing", 0, verbose)
    
    # Initialize local variables instead of using globals
    i = 0
    invalidATags = 0
    progress = 0 
    
    # Initialize data structures
    messages = {}
    wordsUsed = {}
    domainsUsed = {}
    
    log("Initialized data structures", 2, verbose)
    
    # Prepare input and get required values
    startDateObj, endDateObj, pagesToQuery = prepareInput(startDate, iMax, verbose)

    print ('\r\nParsing...')

    domainsUsed['sum'] = {}
    wordsUsed['sum'] = {}

    log(f"Starting main processing loop for {pagesToQuery} pages", 2, verbose)

    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    print("Press ESC or Ctrl+C to interrupt and save data safely...")

    while startDateObj <= endDateObj:

        # Check for interrupt at the beginning of each month
        if interrupt_requested:
            print(f"\nInterrupt detected. Saving data and exiting...")
            break
            
        # Check for ESC key press (non-blocking)
        check_for_escape()
        if interrupt_requested:
            print(f"\nInterrupt detected. Saving data and exiting...")
            break

        currentMonth = startDateObj.strftime('%Y%m')
        currentUrl = urlTemplate + currentMonth
        print(f"Processing month: {currentMonth} - {currentUrl}")
        log(f"Processing month: {currentMonth}", 4, verbose)

        # Check if this month has already been processed
        if not force and isMonthAlreadyProcessed(currentMonth, verbose):
            print(f"Month {currentMonth} already processed, skipping")
            log(f"Month {currentMonth} already processed, skipping", 4, verbose)
            startDateObj = startDateObj + relativedelta(months=+1)
            i += 1
            continue

        domainsUsed[currentMonth] = {}
        wordsUsed[currentMonth] = {}

        showProgress(i, pagesToQuery)
        if inputFile == None:
            url = urlTemplate + currentMonth
            log(f"Fetching from URL: {url}", 6, verbose)
            try:
                html = urllib.request.urlopen(url).read()
                html = html.decode('utf8')
                log(f"Successfully fetched {len(html)} characters", 8, verbose)
            except urllib.error.URLError as e:
                if 'CERTIFICATE_VERIFY_FAILED' in str(e):
                    log("SSL certificate verification failed, retrying without verification", 8, verbose)
                    # Create an SSL context that doesn't verify certificates
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                    html = urllib.request.urlopen(url, context=ssl_context).read()
                    html = html.decode('utf8')
                    log(f"Successfully fetched {len(html)} characters without SSL verification", 8, verbose)
                else:
                    raise
        else:
            inputFileName = '{}{}'.format(currentMonth, inputFile)
            log(f"Reading from local file: {inputFileName}", 6, verbose)
            resInputFile = open(inputFileName, 'r', encoding='utf8')
            html = resInputFile.read()
            resInputFile.close()
            log(f"Successfully read {len(html)} characters from file", 8, verbose)

        putRawHtmlToDisk(html, currentMonth, outputFile, verbose)

        # thats our function to sanitize incoming html, see above comment: if fefe does not close the <a>-tag, our parser
        # tries to close it, but this will affect following list elements, so we try to fix it ourself
        htmlLines = html.splitlines()
        cleanHtmlLines = []
        
        log("Sanitizing HTML for unclosed <a> tags", 6, verbose)
        for line in htmlLines:
            cleanLine = line
            if cleanLine.count('<a') != cleanLine.count('</a>'):
                invalidATags += 1
                log(f"Found unclosed <a> tag in line, fixing...", 8, verbose)
                while cleanLine.count('<a') > cleanLine.count('</a>'):
                    cleanLine += '</a>'
            cleanHtmlLines.append(cleanLine)

        html = ''.join(cleanHtmlLines)
        log(f"HTML sanitization complete. Found {invalidATags} invalid tags so far", 6, verbose)

        # since fefe does not provide closing end tag for <li>, we need to use lxml parser
        # if you want to use html.parser, make sure to define selfClosingTags=["li"]
        # We'll use a different approach to handle the unclosed <li> tags
        log("Parsing HTML with BeautifulSoup", 6, verbose)
        htmlObj = BeautifulSoup(html, features="html.parser")
        
        # Debug: Let's see what the parsed HTML structure looks like
        log(f"HTML structure debug - looking for <ul> tags", 6, verbose)
        allUlTags = htmlObj.find_all('ul')
        log(f"Found {len(allUlTags)} <ul> tags total (recursive=True)", 6, verbose)
        
        # loop through every message and get some date
        unorderedLists = htmlObj.find_all('ul', recursive=False)
        log(f"Found {len(unorderedLists)} unordered lists (recursive=False)", 6, verbose)
        
        # If we don't find any with recursive=False, let's try with recursive=True
        if len(unorderedLists) == 0:
            log("No <ul> found with recursive=False, trying recursive=True", 6, verbose)
            unorderedLists = htmlObj.find_all('ul', recursive=True)
            log(f"Found {len(unorderedLists)} unordered lists (recursive=True)", 6, verbose)
            
            # Let's also check the HTML structure
            if verbose:
                log("HTML structure around <ul>:", 8, verbose)
                for i, ul in enumerate(unorderedLists):
                    log(f"UL {i}: parent = {ul.parent.name if ul.parent else 'None'}", 10, verbose)
                    lis = ul.find_all('li', recursive=False)
                    log(f"  Contains {len(lis)} <li> elements", 10, verbose)
                    
        for listIndex, unorderedList in enumerate(unorderedLists):
            # Check for interrupt at the beginning of each day's processing
            if interrupt_requested:
                print(f"\nInterrupt detected during day processing. Breaking out of day loop...")
                break
                
            log(f"Processing unordered list {listIndex + 1}/{len(unorderedLists)}", 8, verbose)
         
            # Instead of prettify, let's get the raw HTML and split by <li> manually
            # This will handle the unclosed <li> tags properly
            ulHtml = str(unorderedList)
            log(f"Raw UL HTML length: {len(ulHtml)}", 10, verbose)
            
            # Try to find the date header for this list (usually an h3 tag before the ul)
            currentDay = "unknown"
            if unorderedList.find_previous('h3'):
                currentDay = unorderedList.find_previous('h3').get_text().strip()
            
            # Split by <li> tags but keep the <li> tag with each part
            import re
            liParts = re.split(r'(<li[^>]*>)', ulHtml)
            
            # Reconstruct individual <li> elements
            rawMessages = []
            for i in range(1, len(liParts), 2):  # Skip first empty part, then take every second part
                if i + 1 < len(liParts):
                    liTag = liParts[i]
                    liContent = liParts[i + 1]
                    
                    # Remove the closing </ul> tag if present
                    liContent = liContent.replace('</ul>', '')
                    
                    # Create a proper HTML element
                    liHtml = liTag + liContent + '</li>'
                    liElement = BeautifulSoup(liHtml, features="html.parser").find('li')
                    if liElement:
                        rawMessages.append(liElement)
            
            log(f"Found {len(rawMessages)} messages after manual parsing", 10, verbose)

            # Count total messages with ts parameter for progress tracking
            totalMessages = 0
            for msg in rawMessages:
                links = msg.find_all('a')
                for link in links:
                    if link.has_attr('href') and '?ts=' in link['href']:
                        totalMessages += 1
                        break

            print(f"Found {totalMessages} messages to process for {currentDay}")
            processedMessages = 0

            for messageIndex, rawMessage in enumerate(rawMessages):
                # Check for interrupt during message processing
                if interrupt_requested:
                    print(f"\nInterrupt detected during message processing. Breaking out of message loop...")
                    break
                    
                # Periodically check for ESC key (every 10 messages to avoid performance impact)
                if messageIndex % 10 == 0:
                    check_for_escape()
                    if interrupt_requested:
                        print(f"\nInterrupt detected during message processing. Breaking out of message loop...")
                        break
                
                log(f"Processing message {messageIndex + 1}/{len(rawMessages)}", 12, verbose)

                try:
                    message = {
                        'timestamp'     : None,
                        'hexTimestamp'  : None,
                        'quoteCount'    : 0,
                        'wordCount'     : 0,
                        'sourcesCount'  : 0,
                        'url'           : None, # this is more for examination purposes: providing the url to check the results
                        'content'       : None, # the actual message content
                        'contentHtml'   : None, # the raw HTML content
                        'externalSources': []   # metadata from external sources
                    }
                    
                    # Store the raw HTML content
                    message['contentHtml'] = str(rawMessage)
                    log("Stored raw HTML content", 14, verbose)
                    
                    log("Cleaning up quotes", 14, verbose)
                    cleanMessage = cleanUpQuotes(rawMessage)
                    message['quoteCount'] = cleanMessage['count']                
                    cleanMessage = cleanMessage['text']
                    log(f"Found {message['quoteCount']} quotes", 16, verbose)

                    # Store the cleaned text content (without HTML tags)
                    message['content'] = cleanMessage.get_text().strip()
                    log("Stored cleaned text content", 14, verbose)

                    # we add current month to the countWords function, this way we can analyse if used words are changing over the time,
                    # same for countDomains, couple of lines later
                    log("Counting words", 14, verbose)
                    message['wordCount'] = countWords(cleanMessage, currentMonth, wordsUsed, verbose)
                    log(f"Found {message['wordCount']} words", 16, verbose)

                    links = cleanMessage.find_all('a')
                    log(f"Found {len(links)} links", 14, verbose)
                    
                    if len(links) == 0:
                        log("ERROR: No links found in message, skipping", 14, verbose)
                        continue

                    message['url'] = 'https://blog.fefe.de/' + links[0]['href']
                    log(f"Message URL: {message['url']}", 16, verbose)

                    # first get fefes secred timestamp                
                    timestamp_match = re.search('\?ts\=(.*)', links[0]['href'])
                    if not timestamp_match:
                        log("ERROR: No timestamp found in first link, skipping", 14, verbose)
                        continue
                        
                    hexTimestamp = timestamp_match.group(1)
                    message['hexTimestamp'] = hexTimestamp
                    timestamp = getTimestamp(hexTimestamp)            
                    message['timestamp'] = timestamp
                    log(f"Timestamp: {timestamp} (hex: {hexTimestamp})", 16, verbose)

                    # then remove this first link, and get other references from this messages
                    links.pop(0)
                    log("Counting domains", 14, verbose)
                    message['sourcesCount'] = countDomains(links, currentMonth, domainsUsed, verbose)
                    log(f"Found {message['sourcesCount']} external references", 16, verbose)
                    
                    # Parse external sources if requested
                    if parseSource and len(links) > 0:
                        log("Parsing external sources for metadata", 14, verbose)
                        message['externalSources'] = parseExternalSources(links, verbose)
                        log(f"Parsed {len(message['externalSources'])} external sources", 16, verbose)
                    else:
                        message['externalSources'] = []

                    if message['timestamp'] == None:
                        log(f"WARNING: Message has no timestamp, skipping", 14, verbose)
                        continue

                    if message['hexTimestamp'] in messages:
                        log(f"WARNING: Message with id {message['hexTimestamp']} already exists, skipping", 14, verbose)
                        continue

                    messages[message['hexTimestamp']] = message
                    processedMessages += 1
                    print(f"Processing {currentDay}: {processedMessages}/{totalMessages} messages", end='\r')
                    log(f"Message {message['hexTimestamp']} successfully processed", 14, verbose)
                    
                except Exception as e:
                    log(f"ERROR processing message {messageIndex + 1}: {str(e)}", 12, verbose)
                    if verbose:
                        import traceback
                        traceback.print_exc()
                    continue

        print(f"\nCompleted processing month {currentMonth} - {processedMessages} messages processed")
        log(f"Completed processing month {currentMonth}", 4, verbose)

        # let's go to the next month
        startDateObj = startDateObj + relativedelta(months=+1)

        i += 1
        
        if i >= iMax:
            log("Reached iteration limit", 4, verbose)
            print ('\r\nReached limit')
            break

    log("Starting data output", 2, verbose)
    if interrupt_requested:
        print(f"\nSaving data due to interrupt. Total messages processed so far: {len(messages)}")
    putDataToDisk(messages, wordsUsed, domainsUsed, verbose)
    
    if interrupt_requested:
        print("Data saved successfully after interrupt!")
        log(f"Processing interrupted by user. Total messages: {len(messages)}", 0, verbose)
    else:
        log(f"Processing complete. Total messages: {len(messages)}", 0, verbose)
    print ('Found {} invalid <a>-tag(s) w/o href-attribute '.format(invalidATags))

def putRawHtmlToDisk(html, currentMonth, outputFile, verbose):
    
    if outputFile != None:
        fileName = '{}{}'.format(currentMonth, outputFile)
        log(f"Writing raw HTML to file: {fileName}", 8, verbose)
        resOutputFile = open(fileName, 'w', encoding='utf8')
        resOutputFile.write(html)
        resOutputFile.close()
        log(f"Successfully wrote {len(html)} characters to {fileName}", 10, verbose)


def prepareInput(startDate, iMax, verbose):
    
    log("Preparing input parameters", 4, verbose)
    
    endDateObj = datetime.now()
    startDateObj = datetime.strptime(startDate, '%Y-%m')

    timeDiff = relativedelta(endDateObj, startDateObj)

    pagesToQuery = (timeDiff.years * 12) + timeDiff. months

    log(f"Date range: {startDateObj.strftime('%Y-%m')} to {endDateObj.strftime('%Y-%m')}", 6, verbose)
    log(f"Pages to query: {pagesToQuery}, iteration limit: {iMax}", 6, verbose)

    print ('Start month is {}'.format(startDateObj.strftime('%Y-%m')))
    print ('End month is {}'.format(endDateObj.strftime('%Y-%m')))
    print ('Requests are limited to {} iterations (aka months, {} years)'.format(iMax, round(iMax / 12, 2)))

    return startDateObj, endDateObj, pagesToQuery


def showProgress(i, pagesToQuery):
    
    progress = round(100 * i / pagesToQuery)
    print ('{}% '.format(progress), end='')
    # flush output buffer, to get progress in real time
    sys.stdout.flush()

def putDataToDisk(messages, wordsUsed, domainsUsed, verbose):
    
    log("Writing data to disk", 4, verbose)
    
    # put structured and aggregated data to files, lets provide csv and json, just for the case
    log("Writing messages to CSV", 6, verbose)
    writeMessagesToFile(messages, 'messages.csv')
    log("Writing words to CSV", 6, verbose)
    writeCsvToFile(wordsUsed, 'words.csv')
    log("Writing domains to CSV", 6, verbose)
    writeCsvToFile(domainsUsed, 'domains.csv')

    log("Converting data to JSON", 6, verbose)
    jsonMessages = json.dumps(messages, ensure_ascii=False, indent=2)
    jsonWordsUsed = json.dumps(wordsUsed, ensure_ascii=False, indent=2)
    jsonDomainsUsed = json.dumps(domainsUsed, ensure_ascii=False, indent=2)

    log("Writing JSON files", 6, verbose)
    writeJsonToFile(jsonMessages, 'messages.json')
    writeJsonToFile(jsonWordsUsed, 'words.json')
    writeJsonToFile(jsonDomainsUsed, 'domains.json')
    
    log("All data files written successfully", 6, verbose)

def writeCsvToFile(dictionary, fileName):
    
    resFileMessages = open(fileName,'w', encoding='utf8')
    for data in dictionary:
        for field in dictionary[data]:
            resFileMessages.write(str(data))
            resFileMessages.write('\t')
            resFileMessages.write(str(field))
            resFileMessages.write('\t')
            resFileMessages.write(str(dictionary[data][field]))
            resFileMessages.write('\n')
    resFileMessages.close()

def writeMessagesToFile(messages, fileName):
    resFileMessages = open(fileName,'w', encoding='utf8')
    for message in messages:
        for field in messages[message]:
            resFileMessages.write(str(messages[message][field]))
            resFileMessages.write('\t')
        resFileMessages.write('\n')
    resFileMessages.close()

def writeJsonToFile(string, fileName):
    resFile = open(fileName,'w', encoding='utf8')
    resFile.write(string)
    resFile.close()

def cleanUpQuotes(message):
    cleanMessage = {
        'text'  : message,
        'count' : 0
    }
    
    for quote in cleanMessage['text'].find_all('blockquote'):
        quote.decompose()
        cleanMessage['count'] += 1

    return cleanMessage



def parseExternalSources(links, verbose):
    """
    Parse multiple external links to extract metadata.
    Returns a list of metadata dictionaries.
    """
    external_sources = []
    
    for link in links:
        if link.has_attr('href'):
            href = link['href']
        elif link.has_attr('ref'):
            href = link['ref']
        else:
            continue
            
        # Skip self-references
        if href.startswith('/?ts=') or href.startswith('?ts='):
            continue
            
        # Make sure it's a full URL
        if not href.startswith('http'):
            continue
            
        metadata = parseExternalSource(href, verbose)
        if metadata:
            external_sources.append(metadata)
    
    return external_sources

def countDomains(domains, currentMonth, domainsUsed, verbose):    

    log(f"Counting domains for {len(domains)} links", 16, verbose)

    for index, value in enumerate(domains, start=0):

        if value.has_attr('href'):
            href = value['href']
        elif value.has_attr('ref'):
            href = value['ref']
        else:
            log(f"Link {index} has no href or ref attribute, skipping", 18, verbose)
            continue

        # does fefe references himself?
        if href[:5] == '/?ts=' or href[:4] == '?ts=':
            domain = 'self'
        # otherwise it's an external reference
        else: 
            domain = href.split('//')[-1].split('/')[0]
            domain = re.sub('www[\d\.]*', '', domain)

        log(f"Link {index}: {domain}", 18, verbose)

        if domain in domainsUsed[currentMonth]:
            domainsUsed[currentMonth][domain] += 1
        else:
            domainsUsed[currentMonth][domain] = 1

        if domain in domainsUsed['sum']:
            domainsUsed['sum'][domain] += 1
        else:
            domainsUsed['sum'][domain] = 1

    return len(domains)

def countWords(string, currentMonth, wordsUsed, verbose):

    # remove self reference / link to current post
    cleanString = string.getText().replace('[l] ', '')
                    
    # problem: getText() returns all text, also from child elements, and it removes html tags
    # this will connect end of sentences with starting tags, s, e.g.:
    # oder?<b>Update will result in oder?Update
    # so wee ned to find those cases (\w+[.!?]+\w+) and add an aditional space
    # as fefe tends to  exaggerate (usage of 1!1!11!elf!1!), elf will finally be considered as a single word
    # e.g.: oder?!elf!?!?update will be oder?! elf!?!?!? update

    cleanString = re.sub(r'(([\:\.\!\?1]+)([a-zA-Z1-9]+))', r'\2 \3', cleanString)
        
    # splitt the text based on spaces
    # also transform to lower case
    words = cleanString.lower().split()
    
    log(f"Processing {len(words)} words", 16, verbose)

    validWords = 0
    for word in words:
        # remove unwanted stuff
        # strip will only remove pre- and suffixes, but i prefer the stronger reEx replace to 
        # get a cleaner result
        # cleanWord = word.strip(ignoreChars)
        cleanWord = re.sub(ignoreCharsRegEx, '', word)

        # only keep words with at least minWordLenght characters
        # and also ignore "words" starting with a number, because than it is not a word (by my definition) 
        # this will remove a lot of dirt
        if len(cleanWord) >= minWordLength and not cleanWord[0].isdigit():
            validWords += 1
            
            if cleanWord in wordsUsed['sum']:
                wordsUsed['sum'][cleanWord] += 1
            else:
                wordsUsed['sum'][cleanWord] = 1

            if cleanWord in wordsUsed[currentMonth]:
                wordsUsed[currentMonth][cleanWord] += 1
            else:
                wordsUsed[currentMonth][cleanWord] = 1

    log(f"Found {validWords} valid words (min length: {minWordLength})", 18, verbose)
    return len(words)

def getTimestamp(fefeTimestamp):
    # convert hexa decimal value to decimal value
    intTimestamp = int(fefeTimestamp, 16)

    # invert integer by secret timestamp key
    unixTimestamp = intTimestamp ^ timestampKey

    # convert unix timestamp to human readable one
    timestamp = datetime.fromtimestamp(unixTimestamp)

    return timestamp.strftime('%Y-%m-%d %H:%M:%S')

def getParameters():
    
    parser = argparse.ArgumentParser(description='Fefe blog scraper')
    
    parser.add_argument('-s', '--start', 
                        help='what month to start, format is Y-m, e.g. 2005-03')
    
    parser.add_argument('-i', '--input', 
                        help='file name, if provided, script will not load from remote location, date will be pre-pended, if you provide "_data.html", data will be loaded from 201503_data.html')
    
    parser.add_argument('-o', '--output', 
                        help='file name, script will save raw html data into this file, for later use (warning: content will be overwritten), date will be prepended, e.g. 201503_data.html, if you set this to _data.html')
    
    parser.add_argument('-l', '--limit', 
                        type=int, 
                        default=240,
                        help='number to limit requests, each month requires one request, default is 240 (aka 240 months, 20 years), otherwise limit is current month')

    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help='verbose output, will print more information to console')

    parser.add_argument('--parse-source',
                        action='store_true',
                        help='parse external links to extract meta data like titles from linked sources')

    parser.add_argument('--force',
                        action='store_true',
                        help='force reprocessing of months that have already been processed')

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)
    args = parser.parse_args()
    
    startDate = args.start
    inputFile = args.input
    outputFile = args.output
    iMax = args.limit
    verbose = args.verbose
    parseSource = args.parse_source
    force = args.force

    if startDate == None and inputFile == None:
        print ('\r\n!!!Start date or input file are not provided. At least one is required!!! \r\n')
        parser.print_help()
        sys.exit(-1)
    
    return startDate, inputFile, outputFile, iMax, verbose, parseSource, force

if __name__ == '__main__':
     
    startDate, inputFile, outputFile, iMax, verbose, parseSource, force = getParameters()

    getMessages(startDate, inputFile, outputFile, iMax, verbose, parseSource, force)
