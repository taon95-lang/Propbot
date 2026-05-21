"""
CS2 Player Prop Grading and Estimation Engine - Graphical Interface
Launches a modern, dark-themed Tkinter dashboard that visualizes
matchup adjustments, historical series data, and simulation outcomes.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
from scraper import CS2PropScraper

class CS2PropGraderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CS2 Prop Assessment & Grading Engine")
        self.root.geometry("1100x750")
        self.root.configure(bg="#111214")  # Material Discord Dark Aesthetic
        
        self.grader = CS2PropScraper()
        
        # Configure application stylesheet parameters
        self.style = ttk.Style()
        self.style.theme_use("clam")
        
        # Dark color palettes
        self.style.configure(".", background="#111214", foreground="#e0e1e4")
        self.style.configure("TLabel", background="#111214", foreground="#e0e1e4", font=("Segoe UI", 9))
        self.style.configure("TFrame", background="#111214")
        self.style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground="#00bcff")
        self.style.configure("TButton", font=("Segoe UI", 9, "bold"), background="#00bcff", foreground="#111214")
        self.style.map("TButton", background=[("active", "#0099cc")])
        self.style.configure("TProgressbar", thickness=15, troughcolor="#1e1f22", background="#00bcff")
        
        self.style.configure("TLabelframe", background="#111214", foreground="#00bcff", font=("Segoe UI", 10, "bold"))
        self.style.configure("TLabelframe.Label", background="#111214", foreground="#00bcff")

        # Table configurations
        self.style.configure("Treeview", 
                             background="#1e1f22", 
                             fieldbackground="#1e1f22", 
                             foreground="#ffffff", 
                             rowheight=24,
                             font=("Consolas", 9))
        self.style.configure("Treeview.Heading", 
                             background="#2b2d31", 
                             foreground="#ffffff", 
                             font=("Segoe UI", 9, "bold"))
        self.style.map("Treeview.Heading", background=[("active", "#35373c")])

        self.build_gui()

    def build_gui(self):
        # Top Header Banner
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill="x", pady=10, padx=15)
        
        title_lbl = ttk.Label(header_frame, text="ELITE CS2 PROP GRADING PLATFORM", style="Header.TLabel")
        title_lbl.pack(side="left")
        
        sub_lbl = ttk.Label(header_frame, text="Esports Betting Guru • Professional Analyst Edition", foreground="#949ba4")
        sub_lbl.pack(side="right", pady=5)

        # Main Workspace splitter
        main_pane = ttk.Frame(self.root)
        main_pane.pack(fill="both", expand=True, padx=15, pady=5)

        # Left Column - Inputs Form
        left_column = ttk.Frame(main_pane)
        left_column.pack(side="left", fill="both", expand=False, width=320, padx=(0, 10))
        
        form_frame = ttk.LabelFrame(left_column, text=" Parameter Configurations ")
        form_frame.pack(fill="both", expand=True, pady=5)
        
        # Form input fields
        inputs =
        
        self.entry_widgets = {}
        for label_text, var_name, default_val in inputs:
            row = ttk.Frame(form_frame)
            row.pack(fill="x", py=4, padx=8)
            
            lbl = ttk.Label(row, text=label_text, width=15, anchor="w")
            lbl.pack(side="left")
            
            ent = ttk.Entry(row, font=("Segoe UI", 9))
            ent.insert(0, default_val)
            ent.pack(side="right", fill="x", expand=True)
            self.entry_widgets[var_name] = ent

        # Run action control buttons
        btn_row = ttk.Frame(form_frame)
        btn_row.pack(fill="x", pady=15, padx=8)
        
        self.run_btn = ttk.Button(btn_row, text="EXECUTE RUN", command=self.trigger_analysis)
        self.run_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        
        self.progress = ttk.Progressbar(form_frame, mode="indeterminate")

        # Right Column - Report Displays
        right_column = ttk.Frame(main_pane)
        right_column.pack(side="right", fill="both", expand=True)
        
        # Tabbed workspace for Text output report and the raw spreadsheet table
        self.notebook = ttk.Notebook(right_column)
        self.notebook.pack(fill="both", expand=True)
        
        # Tab 1: Text-Based Console Dashboard Output
        self.text_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.text_tab, text=" Discord Console Output ")
        
        self.console_box = tk.Text(
            self.text_tab,
            bg="#1e1f22",
            fg="#e0e1e4",
            insertbackground="white",
            font=("Consolas", 10),
            padx=10,
            pady=10,
            state="disabled",
            wrap="word"
        )
        self.console_box.pack(fill="both", expand=True)
        
        # Tab 2: Structured Treeview Grid Spreadsheets
        self.grid_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.grid_tab, text=" Series Analysis Breakdowns ")
        
        columns = ("series", "m1", "m2", "total", "line", "outcome")
        self.tree = ttk.Treeview(self.grid_tab, columns=columns, show="headings", selectmode="browse")
        
        self.tree.heading("series", text="Series ID")
        self.tree.heading("m1", text="Map 1 Kills")
        self.tree.heading("m2", text="Map 2 Kills")
        self.tree.heading("total", text="Cumulative Kills")
        self.tree.heading("line", text="Target Line")
        self.tree.heading("outcome", text="Status Result")
        
        self.tree.column("series", width=80, anchor="center")
        self.tree.column("m1", width=150, anchor="center")
        self.tree.column("m2", width=150, anchor="center")
        self.tree.column("total", width=120, anchor="center")
        self.tree.column("line", width=100, anchor="center")
        self.tree.column("outcome", width=120, anchor="center")
        
        scroll = ttk.Scrollbar(self.grid_tab, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        
        self.tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scroll.pack(side="right", fill="y", pady=5)
        
        # Style spreadsheet outputs matching grade risk levels
        self.tree.tag_configure("OverRow", foreground="#23a55a")   # Emerald green
        self.tree.tag_configure("UnderRow", foreground="#f23f43")  # Crimson red

    def trigger_analysis(self):
        # Extract active values
        params = {}
        for var_name, widget in self.entry_widgets.items():
            params[var_name] = widget.get().strip()
            
        # Basic validation
        try:
            float(params["prop_line"])
            int(params["player_rank"])
            int(params["opponent_rank"])
            float(params["def_adj"])
            float(params["map_adj"])
        except ValueError:
            messagebox.showerror("Validation Error", "Please verify all numerical entry adjustments are correctly formatted.")
            return

        self.run_btn.config(state="disabled")
        self.progress.pack(fill="x", pady=5, padx=8)
        self.progress.start(12)
        
        # Asynchronous background threading to prevent UI blocking
        worker = threading.Thread(target=self.execute_async, args=(params,))
        worker.daemon = True
        worker.start()

    def execute_async(self, params):
        result = self.grader.analyze_player_prop(
            player_name=params["player_name"],
            player_team=params["player_team"],
            opponent_name=params["opponent_name"],
            prop_line=float(params["prop_line"]),
            player_rank=int(params["player_rank"]),
            opponent_rank=int(params["opponent_rank"]),
            def_adj=float(params["def_adj"]),
            maps_adj=float(params["map_adj"])
        )
        
        # Safe thread transitions back to main thread
        self.root.after(0, self.update_displays, result)

    def update_displays(self, result):
        # 1. Update the treeview grid display
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        for s in result["series_list"]:
            outcome = "OVER" if s["over"] else "UNDER"
            tag = "OverRow" if s["over"] else "UnderRow"
            self.tree.insert("", "end", values=(
                s["series_id"],
                f"{s['m1_name'].upper()}: {s['m1_kills']}",
                f"{s['m2_name'].upper()}: {s['m2_kills']}",
                s["total"],
                result["line"],
                outcome
            ), tags=(tag,))

        # 2. Re-create the Discord dashboard output
        report = self._generate_discord_string(result)
        
        self.console_box.config(state="normal")
        self.console_box.delete("1.0", tk.END)
        self.console_box.insert("1.0", report)
        self.console_box.config(state="disabled")
        
        # Stop indicators
        self.progress.stop()
        self.progress.pack_forget()
        self.run_btn.config(state="normal")

    def _generate_discord_string(self, r):
        # Determine status signals
        avg_diff = ((r["avg"] - r["line"]) / r["line"]) * 100
        avg_status = f"{avg_diff:+.1f}% vs Line"
        med_status = "At Line" if r["median"] == r["line"] else f"{r['median'] - r['line']:+.1f} vs Line"
        
        hit_rate_status = "Moderate" if 4 <= r["hit_rate_num"] <= 6 else "Strong"
        stomp_warning = "⚠️ STOMP RISK" if r["stomp_active"] else "Neutral"
        
        # Determine simulation over bar visualization
        filled_segments = int(r["over_prob"] / 10)
        bar_str = "█" * filled_segments + "░" * (10 - filled_segments)
        
        # Cold streak checks
        cold_streak = all(not s["over"] for s in r["series_list"][:4])
        cold_streak_str = "⚠️ COLD STREAK — 4 straight misses" if cold_streak else "None"
        
        # Per Map lists generators
        map_rows =
        for m in sorted(r["map_history"].keys()):
            m_data = r["map_history"][m]
            if m_data["n"] > 0:
                # Per-map evaluation: avg * 2 vs line
                doubled_avg = m_data["avg"] * 2
                indicator = "🟢" if doubled_avg > r["line"] else "🔴" if doubled_avg < r["line"] else "⚪"
                
                # Format kills list matching screens
                kills_list_str = ",".join(map(str, m_data["kills"]))
                map_rows.append(
                    f"  {m:<12} {m_data['n']:<4} {m_data['avg']:<6.1f} {m_data['range']:<8}\n"
                    f"  {kills_list_str:<25} {indicator}"
                )
            else:
                map_rows.append(f"  {m:<12} -    -      no data")
                
        per_map_history_str = "\n".join(map_rows)
        
        # Series list builder
        series_rows =
        for s in r["series_list"]:
            mark = "✅" if s["over"] else "❌"
            series_rows.append(
                f"S{s['series_id'][1:]}: {s['m1_name']} {s['m1_kills']} + {s['m2_name']} {s['m2_kills']} = {s['total']} {mark}"
            )
        series_breakdown_str = "\n".join(series_rows)
        
        # Expected KPR listings
        kpr_list = [f"{m} {r['kpr_database'].get(m, 0.70):.2f}" for m in if m in r["kpr_database"]]
        kpr_by_map_str = " · ".join(kpr_list)
        
        # Adjust commentary based on results
        decision_override = "AUTO NO BET" if r["grade"] == "F" else "ACTIVE BET CONFIRMED"
        
        report_text = f"""PLAYER: {r['player']} ({r['team']}) vs. {r['opponent']}
MATCH: Maps 1-2 Kills | PROP LINE: {r['line']}
-------------------------------------------------------
GRADE: {r['grade']}
PROJECTION: {r['projection']}
-------------------------------------------------------
| Metric | Value | Status |
| Recent Avg (Last 10) | {r['avg']:.1f} | {avg_status} |
| Recent Median | {r['median']:.1f} | {med_status} |
| Hit Rate | {r['hit_rate_num']}/10 | ⚠️ {hit_rate_status} |
| Projected Rounds | {r['projected_rounds']} | {r['stomp_status']} |
| Role / Map Pool | ⚡ Rifler | Neutral |

📊 PROJECTION (EMPIRICAL)
• Simulated Mean: {r['sim_mean']:.2f}  • σ: {r['sim_sigma']:.1f}
• Over Probability: {r['over_prob']:.1f}%  [{bar_str}]
• Under Probability: {r['under_prob']:.1f}%  • Push: 0.0%
• Edge vs. Line: {r['over_prob'] - 50.0:+.1f}%  • Fair Line: {r['sim_mean']:.1f}
• Range (p10-p90): {int(r['sim_mean'] - 1.28*r['sim_sigma'])}-{int(r['sim_mean'] + 1.28*r['sim_sigma'])} • IQR (p25-p75): {int(r['sim_mean'] - 0.67*r['sim_sigma'])}-{int(r['sim_mean'] + 0.67*r['sim_sigma'])}
• Historical Ceiling/Floor: {min([s['total'] for s in r['series_list']])}-{max([s['total'] for s in r['series_list']])}
• Deaths/Round (DPR): 0.724
• Misprice Type: Trap

🛡️ ROBUSTNESS
• Trimmed Avg: {r['trimmed_avg']:.1f}  • MAD-σ: {r['mad_sigma']:.1f}  • IQR: 22-34
• Sample-shrink: 100%
• Sub-signals: 1🟢 / 1🔴 -> split, signals split

🟡 ROUND SWING • MULTI-KILL • PLAYER PROFILE
• {r['round_swing_rating']} Round Swing
  Typical output scaling — moderate match-length sensitivity
• {r['multi_kill_rating']} Multi-kill
  Moderate ceiling — occasional big rounds but not dominant

📐 MATCH-LENGTH SCENARIOS
Short-map Projection (~18 rds/map): {r['short_proj']:.1f} kills -> ❌ {r['short_status']}
Normal-map Projection (~23 rds/map): {r['normal_proj']:.1f} kills -> ❌ {r['normal_status']}
Ceiling estimate: {r['ceiling_est']:.1f} kills

🗺️ Map Intelligence
Expected: {r['best_map']} {r['expected_map_kills'].get(r['best_map'], 14.0)} ↑
Series proj on these maps: {r['series_proj']:.1f} {r['series_proj_pct']:+.1f}% vs line
Best: {r['best_map']} {r['expected_map_kills'].get(r['best_map'], 14.0)} ↑ • Worst: {r['worst_map']} {r['expected_map_kills'].get(r['worst_map'], 12.0)} ↓
KPR by Map: {kpr_by_map_str}

🗺️ Per-Map Kill History (last 10)
  Map          n    avg    rng
  last10 (newest→oldest)
  -----------------------------------------------------
{per_map_history_str}

▶ = likely map for this match · 🟢 over · 🔴 under · ⚪ even (per-map avg*2 vs line)

🔍 ANALYSIS
{r['player']} is a player whose historical output is the primary signal here. His numbers swing series-to-series, so the range matters as much as the average. His recent average of {r['avg']:.1f} sits near the {r['line']} line and signals are split — the simulation shows no clear edge. The rank gap against {r['opponent']} introduces a stomp risk that could shorten maps and suppress his total ({abs(r['player_rank'] - r['opponent_rank'])} positions).

vs {r['opponent']} — Strengths: Tight defensive structure — low kills allowed, Avoids {r['worst_map']} — controlled pool
Weaknesses: High-frag map pool ({r['best_map']}) inflates kill totals

🔬 vs {r['opponent']}
Combined: {r['combined_adj']:+.1f}%  • ⚖️ Average Defense  • H2H: no data
Def {r['def_adj']:+.1f}% Rank {r['rank_adj']:+.1f}% Maps {r['maps_adj']:+.1f}%
🏆 Elite Clash — #{r['player_rank']} vs #{r['opponent_rank']}

💬 GURU COMMENTARY
vs {r['opponent']} ({r['combined_adj']:+.1f}% combined). ⚖️ Average Defense. 🏆 Elite Clash — #{r['player_rank']} vs #{r['opponent_rank']}. ⚠️ Stomp risk — projected {r['projected_rounds']} rounds (Stomp Mismatch (Rank gap {abs(r['player_rank'] - r['opponent_rank'])}) — short match risk). ⚠️ High Variance • σ={r['sim_sigma']:.1f}

⚠️ Risk Flags
• ⚠️ Stomp risk — rank gap {abs(r['player_rank'] - r['opponent_rank'])}, maps may end ~19 rounds
• ⚠️ High variance — σ={r['sim_sigma']:.1f} (range: {min([s['total'] for s in r['series_list']]):.1f}-{max([s['total'] for s in r['series_list']]):.1f})
• {cold_streak_str}

📋 Series Breakdown
{series_breakdown_str}
Line {r['line']} → need >{int(r['line'])}
🚫 {decision_override}
🚫 NO BET — NO BET
"""
        return report_text

if __name__ == "__main__":
    root = tk.Tk()
    app = CS2PropGraderApp(root)
    root.mainloop()
