# fefeScrape
Parse fefes blog to count words, message and used sources (links to external pages)

This is a Python script that scrapes all content from blog.fefe.de to count words, messages and links to external sources. 

It provides following parameters:

-h print help / available parameters
-s --start start date, expected format is YYYY-MM, e.g. 2010-05
-i --input file name template, when looping through date range, date will be prepended as 201005
-o --output file name template, same as input
-l --limit limit loop to this integer

If you provide output file name, the script will parse the remote location and put all content as HTML into the given output files. One file will be created for each months. If you want to reparse the files, you can provide the same template file name to the parameter output. 


