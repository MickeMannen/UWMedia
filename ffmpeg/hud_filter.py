import json
import cv2
from pathlib import Path

def generate_hud_filter_complex(layout, video_width, video_height):
    """
    Generates an FFmpeg filter_complex string for a HUD skin and linked telemetry elements.
    """
    hud_skin = layout.get("hud_skin")
    if not hud_skin:
        return ""

    path = hud_skin.get("path")
    opacity = hud_skin.get("opacity", 1.0)
    scale = hud_skin.get("scale", 1.0)
    x_pct = hud_skin.get("x_pct", 0.0)
    y_pct = hud_skin.get("y_pct", 0.0)
    
    x_pos = int(x_pct * video_width)
    y_pos = int(y_pct * video_height)

    # Get PNG dimensions for text positioning
    # We need cv2 to get the original size to calculate relative positions correctly
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return ""
    h_orig, w_orig = img.shape[:2]
    w_scaled = w_orig * scale
    h_scaled = h_orig * scale

    filters = []
    
    # Layer 2: Prepare PNG (Assuming it's input [2:v] in color.py)
    # scale -> alpha
    filters.append(f"[2:v]scale={w_scaled}:-1,format=yuva444p,colorchannelmixer=aa={opacity}[hud_bg]")
    
    # Layer 1 & 2 Merge: Overlay PNG onto Video [0:v]
    filters.append(f"[0:v][hud_bg]overlay={x_pos}:{y_pos}[v_hud]")
    
    last_label = "[v_hud]"
    
    # Layer 3+: drawtext filters
    for i, element in enumerate(hud_skin.get("linked_elements", [])):
        field = element.get("field")
        rel_x = element.get("rel_x", 0.0)
        rel_y = element.get("rel_y", 0.0)
        color = element.get("color", "#FFFFFF").replace("#", "0x")
        font_size = int(element.get("font_size", 24))
        
        # Calculate absolute position for drawtext
        abs_x = int(x_pos + (rel_x * w_scaled))
        abs_y = int(y_pos + (rel_y * h_scaled))
        
        # Use a placeholder for the text that FFmpeg can use
        # For a truly dynamic solution, we might need a sidecar metadata file or ASS.
        # But per the prompt, we use drawtext. We'll use the 'text' parameter with a variable.
        # Since we are piping, we might burn the text values into the frame in OpenCV instead,
        # but the prompt specifically asks for this FFmpeg translation.
        
        # If we use FFmpeg's drawtext with a file, we can update the file.
        # But that's slow. Let's assume the text is provided via a metadata key or similar.
        text_val = fr"%{{metadata\:telemetry_{field}}}"
        
        txt_filter = f"drawtext=text='{text_val}':x={abs_x}:y={abs_y}:fontcolor={color}:fontsize={font_size}"
        
        next_label = f"[v_text_{i}]"
        filters.append(f"{last_label}{txt_filter}{next_label}")
        last_label = next_label

    return ";".join(filters)
