#!/usr/bin/env python3
from pathlib import Path
from typing import Any, cast
import sys

from peft import PeftModel
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from transformers.pipelines import pipeline

from prompt_template import build_messages

base_model = "meta-llama/Llama-3.2-3B-Instruct"
experiment_dirs = [
    Path("./fefe-lora-llama3-E1"),
    Path("./fefe-lora-llama3-E2"),
]


def select_model_dtype():
    if torch.cuda.is_available():
        if hasattr(torch.cuda, "is_bf16_supported") and torch.cuda.is_bf16_supported():
            return torch.bfloat16
        return torch.float16
    return torch.float32


def load_model(adapter_path: Path):
    """Load base model and adapter if it exists."""
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
    return pipe, tokenizer


def generate_comment(pipe, tokenizer, prompt_dict: dict) -> str:
    """Generate a comment for the given prompt."""
    from transformers import GenerationConfig

    formatted = tokenizer.apply_chat_template(
        build_messages(prompt_dict, include_target_comment=False),
        tokenize=False,
        add_generation_prompt=True,
    )

    gen_config = GenerationConfig(
        max_new_tokens=200,
        temperature=0.9,
        do_sample=True,
        pad_token_id=tokenizer.eos_token_id,
    )

    output = pipe(
        formatted,
        generation_config=gen_config,
        return_full_text=False,
    )[0]["generated_text"]

    return output.strip()


def main():
    print("=" * 80)
    print("Interactive Model Tester - fefe-lora experiments")
    print("=" * 80)
    print()

    # Check available models
    available_models = [p for p in experiment_dirs if p.exists()]
    if not available_models:
        print("❌ No trained models found!")
        sys.exit(1)

    print(f"✓ Found {len(available_models)} model(s):")
    for i, p in enumerate(available_models, 1):
        print(f"  {i}. {p.name}")
    print()

    # Interactive prompt loop
    while True:
        print("-" * 80)
        print("Enter prompt details (or 'quit' to exit):")
        print()

        topic = input("Topic: ").strip()
        if topic.lower() == "quit":
            break

        if not topic:
            print("Topic cannot be empty!")
            continue

        context = input("Context (optional): ").strip()
        url = input("URL (optional): ").strip()

        prompt_dict = {
            "topic": topic,
            "context": context,
            "url": url,
        }

        print()
        print("Generating comments...")
        print()

        # Load and generate with each model (one at a time to save memory)
        for adapter_path in available_models:
            print(f">>> Loading {adapter_path.name}...")
            try:
                pipe, tokenizer = load_model(adapter_path)
                comment = generate_comment(pipe, tokenizer, prompt_dict)
                print(comment)

                # Free GPU memory
                del pipe, tokenizer
                torch.cuda.empty_cache()
            except Exception as e:
                print(f"❌ Error: {e}")
            print()

        print()


if __name__ == "__main__":
    main()
