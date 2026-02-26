import tkinter as tk
import random
import time

class KaraokeGhostFly:
    def __init__(self, root):
        self.root = root
        self.root.title("Karaoke Ghost Fly Effect")
        self.width, self.height = 1100, 500
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg="#050508", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # --- CẤU HÌNH ---
        self.text_str = "ANH YEU EM NHIEU LAM PHUONG OI"
        self.duration = 4.0        
        
        self.color_wait = "#2d1b33"    # Tím tối (đợi)
        self.color_done = "#00f2ff"    # Xanh Neon (xong)
        self.color_ghost = "#ffffff"   # Màu của chữ bay đi
        
        self.font_family = "Arial"
        self.font_size = 42
        
        self.words = []
        self.ghosts = [] # Chứa các chữ đang bay
        self.setup_phrase()
        self.start_time = time.time()
        self.animate()

    def setup_phrase(self):
        self.canvas.delete("all")
        self.words = []
        self.ghosts = []
        phrase_list = self.text_str.split()
        
        # Đo đạc kích thước để căn giữa
        total_w = 0
        spacing = 30
        temp_widths = []
        for word in phrase_list:
            t_id = self.canvas.create_text(0, -100, text=word, font=(self.font_family, self.font_size, "bold"))
            b = self.canvas.bbox(t_id)
            w = b[2] - b[0]
            temp_widths.append(w)
            total_w += w + spacing
            self.canvas.delete(t_id)
            
        start_x = (self.width - (total_w - spacing)) // 2
        y_pos = self.height // 2
        current_x = start_x
        interval = self.duration / len(phrase_list)

        for i, word in enumerate(phrase_list):
            w_width = temp_widths[i]
            center_x = current_x + (w_width / 2)
            
            word_id = self.canvas.create_text(
                center_x, y_pos, text=word, 
                font=(self.font_family, self.font_size, "bold"),
                fill=self.color_wait, anchor="center"
            )
            
            self.words.append({
                "id": word_id,
                "text": word,
                "target_time": i * interval,
                "cx": center_x,
                "cy": y_pos,
                "status": "wait"
            })
            current_x += w_width + spacing

    def create_ghost(self, item):
        """ Tạo một bản sao của chữ để bay đi """
        ghost_id = self.canvas.create_text(
            item["cx"], item["cy"], 
            text=item["text"], 
            font=(self.font_family, self.font_size, "bold"),
            fill=self.color_ghost, anchor="center"
        )
        # Cấu hình vật lý cho 'hồn' chữ
        self.ghosts.append({
            "id": ghost_id,
            "x": item["cx"],
            "y": item["cy"],
            "vx": random.uniform(-2, 2), # Bay hơi lệch ngang
            "vy": random.uniform(-5, -8), # Bay vút lên trên
            "alpha": 255, # Giả lập độ mờ
            "color_val": 255
        })

    def animate(self):
        elapsed = time.time() - self.start_time
        interval = self.duration / len(self.words)
        
        # 1. Xử lý chữ gốc (Karaoke đổi màu)
        for item in self.words:
            if elapsed >= item["target_time"] and item["status"] == "wait":
                item["status"] = "active"
                self.canvas.itemconfig(item["id"], fill=self.color_done)
                # Kích hoạt hiệu ứng bay
                self.create_ghost(item)

        # 2. Xử lý các chữ đang bay (Ghosts)
        for ghost in self.ghosts[:]:
            ghost["y"] += ghost["vy"]
            ghost["x"] += ghost["vx"]
            ghost["vy"] += 0.2 # Trọng lực nhẹ kéo ngược lại sau khi bay
            
            # Giả lập mờ dần bằng cách đổi màu sát với màu nền
            # Vì Tkinter không có Alpha thực sự cho Text, ta giảm giá trị RGB
            ghost["color_val"] -= 8 
            if ghost["color_val"] <= 10:
                self.canvas.delete(ghost["id"])
                self.ghosts.remove(ghost)
            else:
                # Chuyển từ trắng sang xám tối dần
                c = hex(max(10, ghost["color_val"]))[2:].zfill(2)
                color_hex = f"#{c}{c}{c}"
                self.canvas.itemconfig(ghost["id"], fill=color_hex)
                self.canvas.coords(ghost["id"], ghost["x"], ghost["y"])

        if elapsed < self.duration + 2.0:
            self.root.after(15, self.animate)
        else:
            self.root.after(1000, self.restart)

    def restart(self):
        self.start_time = time.time()
        for g in self.ghosts: self.canvas.delete(g["id"])
        self.ghosts = []
        for item in self.words:
            item["status"] = "wait"
            self.canvas.itemconfig(item["id"], fill=self.color_wait)
        self.animate()

if __name__ == "__main__":
    root = tk.Tk()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"1100x500+{(sw-1100)//2}+{(sh-500)//2}")
    app = KaraokeGhostFly(root)
    root.mainloop()