import urllib.request
from datetime import datetime
from dateutil.relativedelta import *
from bs4 import BeautifulSoup # xml/html parser
import re # regular expresions
import json # to convert python's dictionary to json
import sys, getopt # to get parameters from command line

# where to start, expecting a month here, has to be provided as command line parameter
startDate       = None

# if a local file is provided, we do not send request to remote location, for dry run tests
inputFile       = None

# this is for the raw data
outputFile      = None

# thanks to https://www.netaction.de/datenvisualisierung-von-fefes-blogzeiten/ for figuring this out
timestampKey    = 0xFEFEC0DE

# fefe provides monthly overviews, containing all articles for one month, expected date-format is Ym (201505 for May, 2015)
urlTemplate     = "https://blog.fefe.de/?mon="

# prevent loop to run infinitely, for backup, script stops afert iMax iterations
i               = 0
iMax            = 240

# thats the output dictionary, containing all messages with meta data, timestamps etc.pp.
messages        = {}

# to create a cloud of used words, where the count of occurances defines the size, 
# we count all words fefe is using in an global dictionary
wordsUsed       = {}
# what chars to strip from words, before consider them
ignoreChars     = '()[],;.:\!?"„\''
# using regex for a more cleaner result, ignore the prior line, see description below
ignoreCharsRegEx = '[\W\_]' # \W would not work, because _ is being ignored
# for this word cloud, ignore words with less then minWordLength characters 
minWordLength   = 4
# heads up: as we also strip special chars (,.;) this will also ignore smilies... we dont count, how much Fefe uses smilies.

# let's also count what references fefe makes
domainsUsed     = {}
# sometimes fefe forgets to close a-tags, e.g. blog.fefe.de/?ts=bc6432f7 -  this creates invalid links, apparently, lets count them
# this is also a possible error source, because the xml parse, as in this case mentioned considers the next message as part of the message 
# with the wrong <a>-tag, that's why we are counting it, to give an error-estimation
invalidATags  = 0

def getMessages(startDate):

    # TODO: improve handling of variables / globals
    global iMax, i, invalidATags, progress, pagesToQuery, inputFile, iMax, startDateObj, endDateObj, currentMonth
    
    progress = 0 

    prepareInput()

    print ('\r\nParsing...')

    domainsUsed['sum'] = {}
    wordsUsed['sum'] = {}

    while startDateObj <= endDateObj:

        currentMonth = startDateObj.strftime('%Y%m')

        domainsUsed[currentMonth] = {}
        wordsUsed[currentMonth] = {}

        showProgress()

        if inputFile == None:
            url = urlTemplate + currentMonth
            html = urllib.request.urlopen(url).read()
            html = html.decode('utf8')
        else:
            resInputFile = open('{}{}'.format(currentMonth, inputFile), 'r', encoding='utf8')
            html = resInputFile.read()
            resInputFile.close()

        putRawHtmlToDisk(html)

        # thats our function to sanitize incoming html, see above comment: if fefe does not close the <a>-tag, our parser
        # tries to close it, but this will affect following list elements, so we try to fix it ourself
        htmlLines = html.splitlines()
        cleanHtmlLines = []
        
        for line in htmlLines:
            cleanLine = line
            if cleanLine.count('<a') != cleanLine.count('</a>'):
                invalidATags += 1
                while cleanLine.count('<a') > cleanLine.count('</a>'):
                    cleanLine += '</a>'
            cleanHtmlLines.append(cleanLine)

        html = ''.join(cleanHtmlLines)

        # since fefe does not provide closing end tag for <li>, we need to use lxml parser
        # if you want to use html.parser, make sure to define selfClosingTags=["li"]
        htmlObj = BeautifulSoup(html, features="lxml")
        
        # loop through every message and get some date
        
        for unorderedLists in htmlObj.body.find_all('ul', recursive=False):
         
            unorderedLists.prettify()

            for rawMessage in unorderedLists.find_all('li', recursive=False):

                message = {
                    'timestamp'     : None,
                    'hexTimestamp'  : None,
                    'quoteCount'    : 0,
                    'wordCount'     : 0,
                    'sourcesCount'  : 0,
                    'url'           : None # this is more for examination purposes: providing the url to check the results
                }
                

                cleanMessage = cleanUpQuotes(rawMessage)
                message['quoteCount'] = cleanMessage['count']                
                cleanMessage = cleanMessage['text']

                # we add current month to the countWords function, this way we can analyse if used words are changing over the time,
                # same for countDomains, couple of lines later
                message['wordCount'] = countWords(cleanMessage, currentMonth)

                links = cleanMessage.find_all('a')

                message['url'] = 'https://blog.fefe.de/' + links[0]['href']

                # first get fefes secred timestamp                
                hexTimestamp = re.search('\?ts\=(.*)', links[0]['href']).group(1)
                message['hexTimestamp'] = hexTimestamp
                timestamp = getTimestamp(hexTimestamp)            
                message['timestamp'] = timestamp

                # then remove this first link, and get other references from this messages
                links.pop(0)
                message['sourcesCount'] = countDomains(links, currentMonth)

                if message['timestamp'] == None:
                    print ('A message from {} has no timestamp. This cannot happen.'.format(url))
                    raise SystemExit        

                if message['hexTimestamp'] in messages:
                    print ('The message with the id {} already exists. This cannot happen.'.format(message['hexTimestamp']))
                    raise SystemExit        


                messages[message['hexTimestamp']] = message



        # let's go to the next month
        startDateObj = startDateObj + relativedelta(months=+1)

        i += 1
        
        if i >= iMax:
            print ('\r\nReached limit')
            break

    putDataToDisk()
    
    print ('Found {} invalid <a>-tag(s) w/o href-attribute '.format(invalidATags))

def putRawHtmlToDisk(html):
    
    global outputFile, currentMonth

    if outputFile != None:
        resOutputFile = open('{}{}'.format(currentMonth, outputFile), 'w', encoding='utf8')
        resOutputFile.write(html)
        resOutputFile.close()


def prepareInput():
    
    global inputFile, iMax, startDateObj, endDateObj, pagesToQuery

    endDateObj = datetime.now()
    startDateObj = datetime.strptime(startDate, '%Y-%m')

    timeDiff = relativedelta(endDateObj, startDateObj)

    pagesToQuery = (timeDiff.years * 12) + timeDiff. months

    print ('Start month is {}'.format(startDateObj.strftime('%Y-%m')))
    print ('End month is {}'.format(endDateObj.strftime('%Y-%m')))
    print ('Requests are limited to {} iterations (aka months, {} years)'.format(iMax, round(iMax / 12, 2)))



def showProgress():
    
    global progress, pagesToQuery

    lastProgress = progress
    progress = round(100 * i / pagesToQuery)
    if progress != lastProgress:
        print ('{}% '.format(progress), end='')
        # flush output buffer, to get progress in real time
        sys.stdout.flush()

def putDataToDisk():
    
    global messages, wordsUsed, domainsUsed
    
    # put structured and aggregated data to files, lets provide csv and json, just for the case
    writeMessagesToFile(messages, 'messages.csv')
    writeCsvToFile(wordsUsed, 'words.csv')
    writeCsvToFile(domainsUsed, 'domains.csv')

    
    jsonMessages = json.dumps(messages, ensure_ascii=False)
    jsonWordsUsed = json.dumps(wordsUsed, ensure_ascii=False)
    jsonDomainsUsed = json.dumps(domainsUsed, ensure_ascii=False)

    writeJsonToFile(jsonMessages, 'messages.json')
    writeJsonToFile(jsonWordsUsed, 'words.json')
    writeJsonToFile(jsonDomainsUsed, 'domains.json')

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



def countDomains(domains, currentMonth):    

    for index, value in enumerate(domains, start=0):

        if value.has_attr('href'):
            href = value['href']
        elif value.has_attr('ref'):
            href = value['ref']
        else:
            continue

        # does fefe references himself?
        if href[:5] == '/?ts=' or href[:4] == '?ts=':
            domain = 'self'
        # otherwise it's an external reference
        else: 
            domain = href.split('//')[-1].split('/')[0]
            domain = re.sub('www[\d\.]*', '', domain)

        if domain in domainsUsed[currentMonth]:
            domainsUsed[currentMonth][domain] += 1
        else:
            domainsUsed[currentMonth][domain] = 1

        if domain in domainsUsed['sum']:
            domainsUsed['sum'][domain] += 1
        else:
            domainsUsed['sum'][domain] = 1


    return len(domains)

def countWords(string, currentMonth):

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
            
            if cleanWord in wordsUsed['sum']:
                wordsUsed['sum'][cleanWord] += 1
            else:
                wordsUsed['sum'][cleanWord] = 1

            if cleanWord in wordsUsed[currentMonth]:
                wordsUsed[currentMonth][cleanWord] += 1
            else:
                wordsUsed[currentMonth][cleanWord] = 1

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

    global inputFile, outputFile, startDate, iMax
    
    helpMessage = 'Use it like that: \r\n'
    helpMessage += ' fefe.py -s <start> -i <input> -o <output> -l <limit>\r\n\r\n'
    helpMessage += '  -start: what month to start, format is Y-m, e.g. 2005-03 \r\n'
    helpMessage += '  -input: file name, if provided, script will not load from remote location, date will be pre-pended, if you provide "_data.html", data will be loaded from 201503_data.html \r\n'
    helpMessage += '  -output: file name, script will save raw html data into this file, for later use (warning: content will be overwritten), date will be prepended, e.g. 201503_data.html, if you set this to _data.html \r\n'
    helpMessage += '  -limit: number to limit requests, each month requires one request, default is 240 (aka 240 months, 20 years), otherwise limit is current month'

    try:
        opts, args = getopt.getopt(sys.argv[1:],'hs:i:o:l:',['start=','input=', 'output=', 'limit='])
    except getopt.GetoptError:
        print (helpMessage)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print (helpMessage)
            sys.exit()
        elif opt in ('-s', '--start'):
            startDate = arg
        elif opt in ('-i', '--input'):
            inputFile = arg
        elif opt in ('-o', '--output'):
            outputFile = arg
        elif opt in ('-l', '--limit'):
            iMax = int(arg)

    if startDate == None and inputFile == None:
        print ('\r\n!!!Start date or input file are not provided. At least one is required!!! \r\n')
        print (helpMessage)
        sys.exit(-1)

if __name__ == '__main__':
     
    getParameters()

    getMessages(startDate)
