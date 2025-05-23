<img src="assets/images/cipherseal-841x500.png" width="441" height="300"/>

### Add hidden embedded watermarks to images and text.

Combat AI misinformation and deepfakes with a randomly generated content ID that can be independently verified.

### Usage:

Add `WATERMARKER_SECRET_KEY` to your environment and export it. This should be a strong randomly generated text string.

#### CLI:

*Note:* Only PNG format is currently supported for images. Lossy formats like JPEG may produce unexpected results due to lossy LSB conversion.

Add watermark to image:
`python -m src.service.cli add image path/to/your_sample_image.png -o path/to/watermarked_image.png`

Detect watermark in image:
`python -m src.service.cli detect image path/to/watermarked_image.png`

Add watermark to text: 
`python -m src.service.cli add text path/to/your_sample_text.txt -o path/to/watermarked_text.txt -w "My secret message"`

Detect watermark in text:
`python -m src.service.cli detect text path/to/watermarked_text.txt`
