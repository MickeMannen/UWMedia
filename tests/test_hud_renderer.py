import pytest
from unittest.mock import patch, MagicMock
import numpy as np
from datetime import datetime
from models.dive import Waypoint
from gui.hud_renderer import draw_hud

def test_hud_renderer_text_scaling():
    # Design width is 1000, frame width is 1920 (w_v = 1920)
    # res_scale = 1920 / 1000 = 1.92
    layout = {
        "design_width": 1000,
        "design_height": 800,
        "hud_skin": {
            "type": "shape",
            "width": 200,
            "height": 100,
            "anchor": "TOP_LEFT",
            "linked_elements": [
                {
                    "field": "depth",
                    "font_size": 20,
                    "scale": 1.5,
                    "rel_x": 0.1,
                    "rel_y": 0.2
                }
            ]
        }
    }
    
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    wp = Waypoint(timestamp=datetime.now(), depth=12.5, time_since_start=0)
    
    # 1. Test with render_log=False (should scale the text)
    # Expected final_size: int(20 * 1.92 * 1.5) = 57
    with patch("gui.hud_renderer.get_font") as mock_get_font:
        mock_font = MagicMock()
        from PIL import Image
        dummy_mask = Image.new("L", (10, 10)).im
        mock_font.getmask2.return_value = (dummy_mask, (0, 0))
        mock_font.getmask.return_value = dummy_mask
        mock_get_font.return_value = mock_font
        
        draw_hud(frame, layout, wp, render_log=False)
        
        # Verify that get_font was called with the scaled size
        called_sizes = [args[0] for args, kwargs in mock_get_font.call_args_list]
        assert 57 in called_sizes
        
    # 2. Test with render_log=True (should NOT scale the text)
    # Expected final_size: int(20 * 1.5) = 30
    with patch("gui.hud_renderer.get_font") as mock_get_font:
        mock_font = MagicMock()
        mock_font.getmask2.return_value = (dummy_mask, (0, 0))
        mock_font.getmask.return_value = dummy_mask
        mock_get_font.return_value = mock_font
        
        draw_hud(frame, layout, wp, render_log=True)
        
        # Verify that get_font was called with the unscaled size
        called_sizes = [args[0] for args, kwargs in mock_get_font.call_args_list]
        assert 30 in called_sizes


def test_hud_renderer_user_scale():
    layout = {
        "design_width": 1000,
        "design_height": 800,
        "hud_skin": {
            "type": "image",
            "path": "dummy_path.png",
            "scale": 0.5,
            "anchor": "TOP_LEFT",
            "linked_elements": [
                {
                    "field": "depth",
                    "font_size": 20,
                    "scale": 1.5,
                    "rel_x": 0.1,
                    "rel_y": 0.2
                }
            ]
        }
    }
    
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    wp = Waypoint(timestamp=datetime.now(), depth=12.5, time_since_start=0)
    
    # Mock cv2.imread and get_font to avoid loading actual image
    with patch("cv2.imread") as mock_imread, patch("gui.hud_renderer.get_font") as mock_get_font:
        # Mock image to return a dummy image (e.g. 100x100 shape)
        dummy_img = np.zeros((100, 100, 4), dtype=np.uint8)
        mock_imread.return_value = dummy_img
        
        mock_font = MagicMock()
        from PIL import Image
        dummy_mask = Image.new("L", (10, 10)).im
        mock_font.getmask2.return_value = (dummy_mask, (0, 0))
        mock_font.getmask.return_value = dummy_mask
        mock_get_font.return_value = mock_font
        
        # Test render_log=False:
        # res_scale = 1920 / 1000 = 1.92
        # user_scale = 0.5
        # Expected final_size: int(20 * 0.5 * 1.92 * 1.5) = 28
        draw_hud(frame, layout, wp, render_log=False)
        called_sizes = [args[0] for args, kwargs in mock_get_font.call_args_list]
        assert 28 in called_sizes

    with patch("cv2.imread") as mock_imread, patch("gui.hud_renderer.get_font") as mock_get_font:
        dummy_img = np.zeros((100, 100, 4), dtype=np.uint8)
        mock_imread.return_value = dummy_img
        
        mock_font = MagicMock()
        from PIL import Image
        dummy_mask = Image.new("L", (10, 10)).im
        mock_font.getmask2.return_value = (dummy_mask, (0, 0))
        mock_font.getmask.return_value = dummy_mask
        mock_get_font.return_value = mock_font
        
        # Test render_log=True:
        # res_scale = 1.0 (since render_log=True bypasses res scaling)
        # user_scale = 0.5
        # Expected final_size: int(20 * 0.5 * 1.5) = 15
        draw_hud(frame, layout, wp, render_log=True)
        called_sizes = [args[0] for args, kwargs in mock_get_font.call_args_list]
        assert 15 in called_sizes

