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
