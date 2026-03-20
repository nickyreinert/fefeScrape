#!./.venv/bin/python3

"""
Phase 2: Fine-tune LLaMA-3 with LoRA on prepared Fefe training data.

Supports experiment matrix (E0-E3) via --experiment flag or individual
--packing, --epochs, --lr flags.
"""

import argparse
import warnings
from typing import cast
from urllib3.exceptions import NotOpenSSLWarning

warnings.filterwarnings("ignore", category=NotOpenSSLWarning)

from datasets import Dataset, load_dataset
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import LoraConfig, get_peft_model
from trl import SFTConfig, SFTTrainer
import torch

from prompt_template import build_messages

# Experiment presets: (packing, epochs, lr, sampling_note)
EXPERIMENTS = {
    "E0": {"packing": True,  "epochs": 1, "lr": 2e-5, "note": "baseline"},
    "E1": {"packing": True,  "epochs": 1, "lr": 2e-5, "note": "HTML-first + hard-drop, uniform sampling"},
    "E2": {"packing": True,  "epochs": 1, "lr": 2e-5, "note": "HTML-first + hard-drop + weighted sampling"},
    "E3": {"packing": False, "epochs": 1, "lr": 2e-5, "note": "same as E2, packing off"},
}

base_model = "meta-llama/Llama-3.2-3B-Instruct"


def select_dtype_and_precision():
    if torch.cuda.is_available():
        if hasattr(torch.cuda, "is_bf16_supported") and torch.cuda.is_bf16_supported():
            return torch.bfloat16, {"bf16": True, "fp16": False}
        return torch.float16, {"bf16": False, "fp16": True}
    if torch.backends.mps.is_available():
        return torch.float16, {"bf16": False, "fp16": False}
    return torch.float32, {"bf16": False, "fp16": False}


def main():
    parser = argparse.ArgumentParser(description="Train Fefe LoRA adapter")
    parser.add_argument("--experiment", choices=list(EXPERIMENTS.keys()),
                        help="Use a preset experiment configuration (E0-E3)")
    parser.add_argument("--dataset", default="prepared/fefe_training_data.json", help="Training data path")
    parser.add_argument("--output", default="./fefe-lora-llama3", help="Output directory")
    parser.add_argument("--packing", type=bool, default=None, help="Enable sequence packing")
    parser.add_argument("--epochs", type=int, default=None, help="Number of training epochs")
    parser.add_argument("--lr", type=float, default=None, help="Learning rate")
    args = parser.parse_args()

    # Resolve config: experiment preset, then CLI overrides, then defaults
    if args.experiment:
        preset = EXPERIMENTS[args.experiment]
        packing = preset["packing"] if args.packing is None else args.packing
        epochs = preset["epochs"] if args.epochs is None else args.epochs
        lr = preset["lr"] if args.lr is None else args.lr
        print("Experiment {}: {}".format(args.experiment, preset["note"]))
    else:
        packing = args.packing if args.packing is not None else True
        epochs = args.epochs if args.epochs is not None else 1
        lr = args.lr if args.lr is not None else 2e-5

    print("Config: packing={}, epochs={}, lr={}".format(packing, epochs, lr))

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    tokenizer.pad_token = tokenizer.eos_token

    model_dtype, precision_flags = select_dtype_and_precision()
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=model_dtype,
        low_cpu_mem_usage=True,
    )

    # Required for gradient checkpointing with PEFT on non-CUDA backends
    model.enable_input_require_grads()

    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["q_proj", "v_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)

    dataset = cast(Dataset, load_dataset("json", data_files=args.dataset, split="train"))

    def format_example(example):
        return {
            "text": tokenizer.apply_chat_template(
                build_messages(example, include_target_comment=True),
                tokenize=False,
            )
        }

    dataset = dataset.map(format_example, remove_columns=dataset.column_names)

    output_dir = args.output
    training_args = SFTConfig(
        output_dir=output_dir,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        num_train_epochs=epochs,
        learning_rate=lr,
        logging_steps=1,
        save_strategy="epoch",
        optim="adamw_torch",
        report_to=[],
        bf16=precision_flags["bf16"],
        fp16=precision_flags["fp16"],
        dataset_text_field="text",
        max_length=1024,
        packing=packing,
    )

    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        args=training_args,
        processing_class=tokenizer,
    )

    trainer.train()
    trainer.save_model(output_dir)
    print("Model saved to {}".format(output_dir))


if __name__ == "__main__":
    main()
