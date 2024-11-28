# read file write.jsonl of first line and print "write": 

import json
with open('write.jsonl', 'r') as f:
    first_line = f.readline()
    paragraphs = json.loads(first_line)["write"]
    for p in paragraphs:
        print(p)