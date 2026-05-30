---
id: text/summarize
name: Text Summarizer
version: 1.0.0
description: Summarizes a long document into a short abstract using a deterministic extractive pipeline.
owner:
  handle: t.maker
  team: Knowledge Tools
  contact: t.maker@example.com
tags: [nlp, text, summarization]
capabilityTags: [text.summarize]
inputs:
  - name: document
    type: LongText
    required: true
    description: The source text to summarize.
outputs:
  - name: summary
    type: ShortText
    required: true
    description: A short extractive abstract of the input.
preconditions: [document.nonempty]
mcp:
  server: knowledge-tools
  toolName: summarize
  namespace: example-org
  transport: http
governance:
  visibility: org
  dataClassification: internal
---
# Text Summarizer

Extracts the most salient sentences from a document and returns a short abstract.
Use it when you need a deterministic, repeatable summary of machine-readable text.

## How it works

1. Tokenize the document into sentences.
2. Score sentences by term frequency.
3. Return the top-ranked sentences in original order.
