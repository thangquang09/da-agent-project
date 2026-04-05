from __future__ import annotations

from app.prompts.base import PromptDefinition

CONTEXT_DETECTION_PROMPT_DEFINITION = PromptDefinition(
    name="da-agent-context-detection",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a context analyzer for a Data Analyst Agent.\n"
                "Your job is to classify the context type of the user's query.\n\n"
                "Analyze the query and classify:\n\n"
                "1. context_type: Choose exactly one of:\n"
                '   - "default": No special context needed, standard query flow\n'
                '   - "user_provided": User explicitly provides semantic context about their data/requirements\n'
                '   - "csv_auto": User has uploaded files that need auto-context generation\n'
                '   - "mixed": Both user context and files are present\n\n'
                "2. needs_semantic_context: true or false\n"
                "   - true: The query would benefit from additional semantic context about the data\n"
                "   - false: The query can be answered with just schema information\n\n"
                "Context signals to look for:\n"
                "- User explicitly describing metric definitions or business rules\n"
                '- User referencing uploaded files ("in my CSV", "the file I uploaded")\n'
                '- User asking about data semantics ("what does X mean", "how is Y calculated")\n'
                "- User providing column descriptions or business context\n\n"
                "Return JSON only with this exact shape:\n"
                '{"context_type":"default|user_provided|csv_auto|mixed","needs_semantic_context":true|false}\n\n'
                "No markdown. No extra keys. No explanation."
            ),
        },
        {
            "role": "user",
            "content": (
                "Query: {{query}}\n"
                "{{#if user_semantic_context}}\n"
                "User provided context: {{user_semantic_context}}\n"
                "{{/if}}\n"
                "{{#if uploaded_files}}\n"
                "Uploaded files: {{uploaded_files}}\n"
                "{{/if}}\n\n"
                "Return JSON only."
            ),
        },
    ],
)
