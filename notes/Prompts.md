# User prompt audit log

Append-only record of user development prompts visible during work in this repository. Model extraction templates live separately in `notes/prompts/`. See [AGENTS.md](AGENTS.md) for maintenance rules.

Times use ISO 8601 UTC. Observed time is when the assistant observed/logged the prompt, not an asserted submission time. Git history supports review; this file is not tamper-proof or an automatic archive of other chats.

## P0001

- Observed at: 2026-11-13T13:12:00Z (Europe/London: 2026-11-13 13:12:00 GMT).
- Timestamp provenance: tool clock at first repository inspection; original submission timestamp unavailable.
- Author: user.
- Scope: initial architecture request; no sheet attachments supplied.

```text
The big picture of what I want to build is a pdf/ image extraction tool that pics out rows from inventory removal sign out sheets and neatly outputs these rows into csv/ xlsx files. There will be a human in the loop processing element where some row(s) in a file(s) can be flagged.&#x20;

This is my initial instinct on how to build this please challenge me / tell me if there are any architectural improvements etc. that I can make.&#x20;

I envision these basic steps:&#x20;



1. Document upload (PDF and image compatible)
2. Vision LLM extraction to recognize rows, handwriting and repetition markers. (feel free to suggest some models to start off with). Raw extraction phase.&#x20;
3. A deterministic processing pipeline with rules in place to assign risk.
4. Human review, editing and approval processes.&#x20;
5. Finally, approved csv output



the basic file structure that I am envisioning is as follows:



app.py

extractor.py

schemas.py

resolver.py

validator.py



prompt folder



samples folder



outputs folder



tests folder



.env file

.env.example file

requirements.txt

README.md file (use this file to help track deployment commands etc.)

Prompts.md file

DESIGN.md (keeps track of architctural decisions)



in the prompts.md file, i want you to keep track of every prompt that I submit. include the time of the prompt as well. it needs to be auditable for reviewers. 
```

## P0002

- Observed at: 2026-11-13T13:20:44Z.
- Timestamp provenance: tool clock during repository inspection; original submission timestamp unavailable.
- Author: user.

```text
okay apply the suggested file/folder structure as suggested.
```

## P0003

- Observed at: 2026-11-13T13:22:59Z.
- Timestamp provenance: tool clock during repository inspection; original submission timestamp unavailable.
- Author: user.

```text
organize the markdown files except for the README.md into a folder called notes. 
```

## P0004

- Observed at: 2026-11-13T13:32:01Z.
- Timestamp provenance: tool clock during repository inspection; original submission timestamp unavailable.
- Author: user.

```text
one thing to note moving forward. We will be getting potentially different looking pictures/ pdfs in terms of how the information is structured. But there are common fields that we will need to extract an output. 

The common fields are as follows: 

Quantity · Price · Description · Person name · Job site · Job name · Job # · Date.

The above strictly will be what we output. However we will also have a similar entity such as 

Quantity · Price · Description · Person name · Job site · Job name · Job # · Date · acceptance level (three categories that will be derived on rules yet to come).

Implement these entities using pydantic etc. one time and keep in mind this structure as we continue to build. 
```

## P0005

- Observed at: 2026-11-13T13:45:12Z.
- Timestamp provenance: tool clock during repository inspection; original submission timestamp unavailable.
- Author: user.

```text
okay, actually we probably need to beef up how we track extracted fields from the LLM and cautious inputs in general. We should probably track inherited fields, cancelled rows, uncertain fields and general notes. We need to be able to audit what the LLM was thinking correct? 

might as well add a model to keep track of the page itself and its rows and lay out notes. 

should we add a source row as well?  

For all code that you write, make sure it is as simple as possible while getting the requested task done.
```

## P0006

- Observed at: 2026-11-13T13:58:34Z.
- Timestamp provenance: tool clock during repository inspection; original submission timestamp unavailable.
- Author: user.
- Referenced draft: `prompts/extraction.txt`, inspected during this review.

```text
okay. take a look at the proposed prompt I came up with by querying chatgpt. 

Given the context you know about the project so far and the schema structures, propose and enhancements if any to the prompt. 
```

## P0007

- Observed at: 2026-11-13T14:03:14Z.
- Timestamp provenance: tool clock during repository inspection; original submission timestamp unavailable.
- Author: user.

```text
okay one thing that I think we have forgotten, we eventually need to track runs to not just the model but other configs such as the prompt version etc. Please implement that as needed.
```

## P0008

- Observed at: 2026-11-13T14:11:58Z.
- Timestamp provenance: tool clock during repository inspection; original submission timestamp unavailable.
- Author: user.

```text
In extractor.py fill out the necessary code to be able to actually call a model etc. Make sure that the results are saved one time. 

Some example code: 

import os
import base64
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from schemas import PageExtraction

load_dotenv()

client = OpenAI()

PROMPT = Path(
    "prompts/extraction.txt"
).read_text()


def extract_image(image_bytes: bytes) -> PageExtraction:
    encoded = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    response = client.responses.parse(
        model=os.getenv("VISION_MODEL", "gpt-5.4-mini"),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": PROMPT,
                    },
                    {
                        "type": "input_image",
                        "image_url": (
                            "data:image/png;base64,"
                            + encoded
                        ),
                        "detail": "high",
                    },
                ],
            }
        ],
        text_format=PageExtraction,
    )

    if response.output_parsed is None:
        raise RuntimeError(
            "Model returned no valid extraction"
        )

    return response.output_parsed

import json
from pathlib import Path

result = extract_image(image.read_bytes())

Path("outputs/raw/sheet3.json").write_text(
    result.model_dump_json(indent=2)
)
```

## P0009

- Observed/logged at: 2026-11-13T14:21:21Z.
- Timestamp provenance: recorded retrospectively during the next repository task; original submission and observation timestamps unavailable.
- Author: user.

```text
okay give me a quick terminal command to be able to test this. 
```

## P0010

- Observed at: 2026-11-13T14:21:21Z.
- Timestamp provenance: tool clock during repository inspection; original submission timestamp unavailable.
- Author: user.

```text
got this error code: 

(base) luisweekes@Mac automated-inventory-tracker % .venv/bin/python extractor.py 'samples/Inventory Sheet 3.png'
Extraction failed; inspect /Users/luisweekes/Code/Inventory-tracker/automated-inventory-tracker/data/runs/3ac36bf9-0437-4868-8c8e-545501baadf1/manifest.json
(base) luisweekes@Mac automated-inventory-tracker % 
```

## P0011

- Observed at: 2026-11-13T14:28:48Z.
- Timestamp provenance: tool clock during repository inspection; original submission timestamp unavailable.
- Author: user.

```text
okay in data/runs etc. make an initial csv outpuit file so that we can easily see initial results. 
```

## P0012

- Observed at: 2026-11-13T14:33:24Z.
- Timestamp provenance: tool clock during repository inspection; original submission timestamp unavailable.
- Author: user.

```text
given that this is a small project, we do want to have everything in the data folder committed to github.
```

## P0013

- Observed at: 2026-11-13T14:36:52Z.
- Timestamp provenance: tool clock during repository inspection; original submission timestamp unavailable.
- Author: user.

```text
under runs, have them in chronological order by date time (add thos eproper markings to whcihever file)
```

## P0014

- Observed at: 2026-11-13T14:45:08Z.
- Timestamp provenance: tool clock during repository inspection; original submission timestamp unavailable.
- Author: user.

```text
okay some patterns that I am seeing right now. we need to make sure that we note when a row is highlighted or crossed out (change the prompt?). Also, it appears that for sheet 3, the model correctly pics up that an empty space means a ditto. We need to mark these inferences--make sure that they are noted in the relevant area so that we can flag these issues down the line. 
```
