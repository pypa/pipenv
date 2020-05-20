# PEEP-044: safety-db integration, squelch, and output.

pipenv check needs offline, ci, and other output capabilities.

☤

Not everyone can utilize pipenv check and access the internet. Safety check knew this 
and that is why they created safety-db. This repository contains a json database that
is updated monthly. Safety check allows you to pass a --db flag that is a local directory
containing that database. Safety check also allows you to pass --json, --bare, and 
--full-report. Pipenv check has their own way of displaying the results that is why I
believe there should be a --output flag that allows users to specify json, bare, 
and full-report from safety check and default for the current pipenv check output.
Currently, pipenv check has a lot of stdout messages and makes it harder to pipe
the results into something to be checked (especially for continuous integration 
pipelines). That is why adding a --squelch switch is also important. This will be 
default False (display all stdout); however, the user has the option to add the 
--squelch switch to make the output only come from safety check. 

## Current implementation:
### Example 1
``` bash
pipenv check
Checking PEP 508 requirements…
Passed!
Checking installed package safety…
25853: insecure-package <0.2.0 resolved (0.1.0 installed)!
This is an insecure package with lots of exploitable security vulnerabilities.
```
### Example 2
``` bash
pipenv check | jq length
parse error: Invalid numeric literal at line 1, column 9
```

## Future implementation:
### Example 1
``` bash
pipenv check --db /Users/macbookpro/workspace/test/safety-db/data/ --output json --squelch 
[
    [ 
        "insecure-package",
        "<0.2.0",
        "0.1.0",
        "This is an insecure package with lots of exploitable security vulnerabilities.",
        "25853"
    ]
]
```
### Example 2
``` bash
pipenv check --db /Users/macbookpro/workspace/test/safety-db/data/ --output json --squelch | jq length
1
```
