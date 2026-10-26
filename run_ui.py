"""Запуск UI с анимацией и интерактивным драфтом."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from ui.game_ui import GameUI

print("Starting interactive AutoBattler...")
print("Draft keys: W=Buy S=Sell D=Place F=Remove R=Roll N=Next Enter=Done")
print("Battle keys: SPACE=Pause +/-=Speed ESC=Quit")

ui = GameUI(width=1200, height=800)
ui.run_interactive_match(seed=42, enemy_bot="balanced")
print("Game finished!")
