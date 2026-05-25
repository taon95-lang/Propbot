def data_embed(data, line, opponent):

    e = discord.Embed(
        color=BRAND,
        description=header(
            data,
            line,
            opponent,
            "Kills"
        )
    )

    raw = []

    for row in safe_list(data.get("Raw maps"))[:14]:

        row = safe_dict(row)

        raw.append(
            f"`{safe_str(row.get('map_name')):<9} "
            f"{safe_str(row.get('kills'))}-{safe_str(row.get('deaths'))} "
            f"HS {safe_str(row.get('headshots'))} "
            f"R {safe_str(row.get('rounds'))} "
            f"vs {safe_str(row.get('opponent'))[:12].upper()}`"
        )

    paired = []

    for row in safe_list(data.get("Paired series rows"))[:10]:

        row = safe_dict(row)

        kills = num(row.get("kills"))

        emoji = "🟢" if kills > line else "🔴"

        paired.append(
            f"{emoji} **{safe_str(row.get('opponent')).upper()}** "
            f"({safe_str(row.get('date'))}) — "
            f"{int(kills)}K {safe_str(row.get('headshots'))}HS "
            f"{safe_str(row.get('rounds'))}R | "
            f"{safe_str(row.get('map1'))} + {safe_str(row.get('map2'))}"
        )

    pmap = []

    for m, vals in safe_dict(data.get("Per-map averages")).items():

        vals = safe_dict(vals)

        pmap.append(
            f"`{safe_str(m):<10} "
            f"{safe_str(vals.get('avg_kills'))}K • "
            f"{safe_str(vals.get('avg_kpr'))} KPR • "
            f"{safe_str(vals.get('sample_size'))} maps`"
        )

    e.add_field(
        name="📋 RAW MAP DATA",
        value=trim_lines(raw),
        inline=False
    )

    e.add_field(
        name="🎯 PAIRED SERIES (M1+M2)",
        value=trim_lines(paired),
        inline=False
    )

    e.add_field(
        name="📊 HLTV VERIFIED STATS",
        value=(
            f"**Rating 3.0:** `{safe_str(data.get('Rating 3.0'))}`\n"
            f"**KPR:** `{safe_str(data.get('KPR'))}`\n"
            f"**DPR:** `{safe_str(data.get('DPR'))}`\n"
            f"**ADR:** `{safe_str(data.get('ADR'))}`\n"
            f"**KAST:** `{safe_str(data.get('KAST'))}`\n"
            f"**Impact:** `{safe_str(data.get('Impact'))}`\n"
            f"**HS %:** `{safe_str(data.get('Recent HS %'))}`\n"
            f"**HS Avg M1+M2:** `{safe_str(data.get('Recent HS Average'))}`"
        ),
        inline=False
    )

    e.add_field(
        name="🗺️ MAP POOL / KPR BY MAP",
        value=trim_lines(pmap),
        inline=False
    )

    e.set_footer(
        text="DATA tab • raw HLTV-derived sample"
    )

    return e


def context_embed(data, line, opponent):

    e = discord.Embed(
        color=PANEL,
        description=header(
            data,
            line,
            opponent,
            "Kills"
        )
    )

    h2h = safe_dict(data.get("H2H Data"))
    likely = safe_dict(data.get("Likely maps"))
    veto = safe_list(data.get("Veto"))

    maps = []

    for k, v in likely.items():
        maps.append(f"**{k}:** `{v}`")

    e.add_field(
        name="🎮 MATCH CONTEXT & ROLE",
        value=(
            f"**Role:** `{safe_str(data.get('Role'))}`\n"
            f"**Team:** `{safe_str(data.get('Team'))}`\n"
            f"**Team Rank:** `{safe_str(data.get('Team ranking'))}`\n"
            f"**Opponent Rank:** `{safe_str(data.get('Opponent ranking'))}`\n"
            f"**Odds:** `{safe_str(data.get('Match odds'))}`\n"
            f"**Moneyline:** `{safe_str(data.get('Moneyline'))}` / "
            f"`{safe_str(data.get('Moneyline american'))}`"
        ),
        inline=False
    )

    e.add_field(
        name="🎯 KEY FACTORS",
        value=(
            f"**Likely Maps:** {trim_lines(maps, 500)}\n"
            f"**Hit Rate:** `{safe_str(data.get('Hit rate'))}`\n"
            f"**Average:** `{safe_str(data.get('Recent average'))}`\n"
            f"**Median:** `{safe_str(data.get('Recent median'))}`\n"
            f"**Projection:** `{safe_str(data.get('Recent projection'))}`"
        ),
        inline=False
    )

    e.add_field(
        name="📚 H2H / SIMILAR TEAMS",
        value=(
            f"**Similar Teams:** `{safe_str(data.get('Similar teams'))}`\n"
            f"**H2H Sample:** `{safe_str(h2h.get('h2h_sample_size'))}`\n"
            f"**H2H Avg Kills:** `{safe_str(h2h.get('h2h_avg_kills'))}`\n"
            f"**H2H Avg HS:** `{safe_str(h2h.get('h2h_avg_headshots'))}`\n"
            f"**Note:** `{safe_str(h2h.get('h2h_note'))}`"
        ),
        inline=False
    )

    e.add_field(
        name="📝 VETO / MAP NOTES",
        value=trim_lines(veto),
        inline=False
    )

    e.set_footer(
        text="CONTEXT tab • role, maps, H2H, opponent profile"
    )

    return e


# =========================================================
# REPLACE YOUR CURRENT PropView CLASS WITH THIS
# =========================================================

class PropView(discord.ui.View):

    def __init__(self, data, line, opponent):

        super().__init__(timeout=1800)

        self.data = data
        self.line = line
        self.opponent = opponent

    async def interaction_check(self, interaction):
        return True

    async def on_timeout(self):

        for item in self.children:
            item.disabled = True

    async def swap(self, interaction, embed):

        try:

            if interaction.response.is_done():

                await interaction.edit_original_response(
                    embed=embed,
                    view=self
                )

            else:

                await interaction.response.edit_message(
                    embed=embed,
                    view=self
                )

        except Exception as e:
            print(f"VIEW ERROR: {e}", flush=True)

    @discord.ui.button(
        label="GRADE",
        style=discord.ButtonStyle.primary,
        emoji="☠️"
    )
    async def grade_btn(self, interaction, button):

        await self.swap(
            interaction,
            grade_embed(
                self.data,
                self.line,
                self.opponent
            )
        )

    @discord.ui.button(
        label="DATA",
        style=discord.ButtonStyle.secondary,
        emoji="📊"
    )
    async def data_btn(self, interaction, button):

        await self.swap(
            interaction,
            data_embed(
                self.data,
                self.line,
                self.opponent
            )
        )

    @discord.ui.button(
        label="CONTEXT",
        style=discord.ButtonStyle.secondary,
        emoji="🧠"
    )
    async def context_btn(self, interaction, button):

        await self.swap(
            interaction,
            context_embed(
                self.data,
                self.line,
                self.opponent
            )
        )
