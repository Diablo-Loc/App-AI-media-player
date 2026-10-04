# Frozen original method from 4148c138c1e38f4959574caf925f1c86dbcca339.
# This is a source-contract fixture, not an application module.
def update_play_state(self, is_playing):
    self.btn_play.setText("⏸" if is_playing else "▶")
    self.btn_play.setStyleSheet("background-color: #1DB954;" if is_playing else "background-color: white;")
