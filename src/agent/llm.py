from agent.config import MODEL_PATH, LOAD_IN_4BIT

_model = None
_tokenizer = None


def _load_local():
    """Loads on the first call only, the model stays in memory afterwards."""
    global _model, _tokenizer

    if _model is not None:
        return

    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig

    _tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)

    kwargs = {
        "device_map": "auto",
        "local_files_only": True,
    }

    if LOAD_IN_4BIT and torch.cuda.is_available():
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
        )

    _model = AutoModelForCausalLM.from_pretrained(MODEL_PATH, **kwargs)
    device = "GPU" if torch.cuda.is_available() else "CPU"
    print(f"Model loaded from {MODEL_PATH} ({device})")


def ask_llm(messages, max_new_tokens=256):
    _load_local()

    import torch

    prompt = _tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = _tokenizer(prompt, return_tensors="pt")
    device = _model.get_input_embeddings().weight.device
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.inference_mode():
        outputs = _model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=_tokenizer.eos_token_id,
        )

    new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
    return _tokenizer.decode(new_tokens, skip_special_tokens=True).strip()