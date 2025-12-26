#!/usr/bin/env python3
"""
Script to resize all JPG and PNG images in z-archive to 300x300 pixels.
For non-square images, crops the middle square portion.
PNG files are converted to JPEG format.
Saves resized images to the resize-small folder.
"""

import os
from pathlib import Path
from PIL import Image

def find_image_files(root_dir):
    """Find all JPG/JPEG and PNG files recursively in the directory, excluding resize-small folder."""
    image_files = []
    root_path = Path(root_dir)
    
    # Find all .jpg, .jpeg, and .png files recursively, excluding resize-small folder
    for ext in ['*.jpg', '*.jpeg', '*.JPG', '*.JPEG', '*.png', '*.PNG']:
        for file_path in root_path.rglob(ext):
            # Exclude files in resize-small folder
            if 'resize-small' not in str(file_path):
                image_files.append(file_path)
    
    # Sort for consistent ordering
    return sorted(image_files)

def resize_image(input_path, output_path, size=(300, 300)):
    """Resize an image to the specified size, cropping middle square if not square."""
    try:
        with Image.open(input_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            width, height = img.size
            
            # If image is not square, crop the middle square
            if width != height:
                # Determine the size of the square (use the smaller dimension)
                square_size = min(width, height)
                
                # Calculate crop box to get middle square
                if width > height:
                    # Landscape: crop from sides
                    left = (width - square_size) // 2
                    top = 0
                    right = left + square_size
                    bottom = height
                else:
                    # Portrait: crop from top/bottom
                    left = 0
                    top = (height - square_size) // 2
                    right = width
                    bottom = top + square_size
                
                # Crop to middle square
                img = img.crop((left, top, right, bottom))
            
            # Resize the (now square) image to target size
            img = img.resize(size, Image.Resampling.LANCZOS)
            
            img.save(output_path, 'JPEG', quality=85)
            return True
    except Exception as e:
        print(f"Error processing {input_path}: {e}")
        return False

def main():
    # Get the z-archive directory (parent of this script's directory)
    script_dir = Path(__file__).parent
    z_archive_dir = script_dir.parent
    output_dir = script_dir
    
    print(f"Searching for image files (JPG/PNG) in: {z_archive_dir}")
    print(f"Output directory: {output_dir}")
    
    # Find all image files
    image_files = find_image_files(z_archive_dir)
    
    if not image_files:
        print("No image files found in z-archive directory.")
        return
    
    print(f"Found {len(image_files)} image file(s)")
    print(f"Processing all {len(image_files)} file(s)...")
    
    # Process each file
    success_count = 0
    for i, image_file in enumerate(image_files, 1):
        # Create output filename - convert PNG to JPG extension
        relative_path = image_file.relative_to(z_archive_dir)
        output_name = relative_path.stem + '.jpg'  # Always save as .jpg
        output_path = output_dir / output_name
        
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_type = "PNG" if image_file.suffix.lower() == '.png' else "JPG"
        is_png = image_file.suffix.lower() == '.png'
        print(f"[{i}/{len(image_files)}] Processing {file_type}: {image_file.name}")
        
        if resize_image(image_file, output_path):
            success_count += 1
            print(f"  ✓ Saved to: {output_path}")
            
            # Delete original PNG file after successful conversion
            if is_png:
                try:
                    image_file.unlink()
                    print(f"  ✓ Deleted original PNG: {image_file.name}")
                except Exception as e:
                    print(f"  ⚠ Warning: Could not delete {image_file.name}: {e}")
        else:
            print(f"  ✗ Failed to process: {image_file.name}")
    
    print(f"\nCompleted! Successfully processed {success_count}/{len(image_files)} images.")

if __name__ == "__main__":
    main()

