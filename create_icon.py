from PIL import Image, ImageDraw, ImageFont
import os

# Create icon - black box with KOBEL text
size = 512
img = Image.new('RGB', (size, size), color='black')
draw = ImageDraw.Draw(img)

# Try to use a bold font, fall back to default if not available
try:
    font = ImageFont.truetype("arialbd.ttf", 160)
except:
    font = ImageFont.load_default()

# Calculate text position to center it
text = "KOBEL"
bbox = draw.textbbox((0, 0), text, font=font)
text_width = bbox[2] - bbox[0]
text_height = bbox[3] - bbox[1]
x = (size - text_width) // 2
y = (size - text_height) // 2

# Draw white text
draw.text((x, y), text, fill='white', font=font)

# Save as ICO file
icon_path = os.path.join(os.path.dirname(__file__), 'kobel_icon.ico')
img.save(icon_path, format='ICO', sizes=[(512, 512), (256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
print(f"Icon saved to: {icon_path}")
