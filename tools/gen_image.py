# tools/gen_image.py
# Generates a professional AI-themed blog cover image using HuggingFace FLUX.1-schnell.
# Falls back gracefully to None so the caller can try alternative sources.

import os
from pathlib import Path

def generate_cover_image(
    headline: str,
    image_theme: str = "artificial intelligence technology",
    output_dir: str = "output"
) -> str | None:
    """
    Generate a blog cover image using FLUX.1-schnell via HuggingFace Serverless Inference.
    
    - Uses the free HuggingFace Serverless Inference API (no billing required).
    - Requires HF_TOKEN env var. Set it in .env as HF_TOKEN=hf_...
    - Saves the image to `output_dir/cover.png` and returns the relative file path.
    - Returns None on any error so caller can fall back to other methods.

    Args:
        headline: The top story's headline (used to tailor the prompt).
        image_theme: 2-4 word image theme from the LLM (e.g. "AI funding robotics").
        output_dir: Directory to save the generated image.
    
    Returns:
        Relative file path to the saved image, or None on failure.
    """
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("  [Image] HF_TOKEN not set, skipping AI image generation.")
        return None

    try:
        from huggingface_hub import InferenceClient
        from PIL import Image

        # Build a highly detailed, editorial-quality prompt
        prompt = (
            f"Professional tech blog cover image, cinematic hero shot, "
            f"photorealistic or flat vector design, bold modern colors, "
            f"NO text, NO words, NO letters, NO labels anywhere in image, "
            f"16:9 aspect ratio, ultra high quality, editorial style. "
            f"Theme: {image_theme}. "
            f"Context: {headline[:120]}"
        )

        print(f"  [Image] Generating AI cover image via HuggingFace (FLUX.1-schnell)...")

        # Use HuggingFace's free Serverless Inference API
        client = InferenceClient(
            provider="hf-inference",  # Free serverless inference tier
            api_key=hf_token,
        )

        image: Image.Image = client.text_to_image(
            prompt=prompt,
            model="black-forest-labs/FLUX.1-schnell",
        )

        # Save the generated image
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        output_path = os.path.join(output_dir, "cover.png")
        image.save(output_path)
        
        print(f"  [Image] AI image saved to {output_path}")
        return output_path

    except ImportError:
        print("  [Image] huggingface_hub or Pillow not installed. Run: pip install huggingface_hub Pillow")
        return None
    except Exception as e:
        print(f"  [Image] HuggingFace generation failed: {e}")
        return None


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    result = generate_cover_image(
        headline="Advanced Machine Intelligence Raises $1.03 Billion to Develop Reliable AI",
        image_theme="artificial intelligence funding robotics",
    )
    if result:
        print(f"Generated image at: {result}")
    else:
        print("Image generation failed, check HF_TOKEN and dependencies.")