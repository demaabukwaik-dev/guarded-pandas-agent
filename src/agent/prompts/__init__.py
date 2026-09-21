def build_prompt(system_prompt, user_prompt, context=None):
    """Shape only: system + user.
    Context (schema, state, columns) is appended to the system message
    """

    if context:
        system_prompt = f"{system_prompt}\n\n{context}"

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt}
    ]