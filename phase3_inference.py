#!./.venv/bin/python3
from pathlib import Path
from typing import Any, cast

from peft import PeftModel
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from transformers.pipelines import pipeline

from prompt_template import build_messages

base_model = "meta-llama/Meta-Llama-3-8B-Instruct"
adapter_path = Path("./fefe-lora-llama3")


def select_model_dtype():
    if torch.cuda.is_available():
        if hasattr(torch.cuda, "is_bf16_supported") and torch.cuda.is_bf16_supported():
            return torch.bfloat16
        return torch.float16

    return torch.float32


tokenizer = AutoTokenizer.from_pretrained(base_model)
tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    base_model,
    device_map="auto",
    dtype=select_model_dtype(),
)

if adapter_path.exists():
    model = PeftModel.from_pretrained(model, str(adapter_path))

pipe = cast(Any, pipeline("text-generation", model=cast(Any, model), tokenizer=tokenizer))

prompt = {
    "topic": "Innenministerium plant neue Chatkontrolle",
    "context": "Diskutiert wird eine Ausweitung automatisierter Überwachung privater Kommunikation.",
    "url": "",
}

formatted = tokenizer.apply_chat_template(
    build_messages(prompt, include_target_comment=False),
    tokenize=False,
    add_generation_prompt=True,
)

output = pipe(
    formatted,
    max_new_tokens=200,
    temperature=0.9,
    do_sample=True,
    return_full_text=False,
    pad_token_id=tokenizer.eos_token_id,
)[0]["generated_text"]

print(output.strip())
