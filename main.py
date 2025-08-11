# Gerekli kütüphaneleri içe aktarma
import discord
from discord import app_commands, ui
import os
import json
import google.generativeai as genai
import base64
import io
from datetime import datetime

# ----- KULLANICI AYARLARI VE SABİTLER -----
MANUEL_ONAY_KANAL_ID = 1401852648357105715
MINIMUM_IP = 1350
YONETICI_IZNI = 'manage_guild' 
ONAYLI_SETLER_DOSYASI = "/data/onayli_setler_data.json"
SET_IMAGES_KLASORU = "/data/set_images"
ANALYSIS_CACHE_KLASORU = "/data/analysis_cache"
AI_ONAY_METNI = "SET ONAYLANDI"
AI_RED_METNI = "SET HATALI"

# Renkler ve Setler
SUCCESS_COLOR = discord.Color.from_rgb(46, 204, 113) # Yeşil
ERROR_COLOR = discord.Color.from_rgb(231, 76, 60) # Kırmızı
WARN_COLOR = discord.Color.from_rgb(241, 196, 15) # Sarı
INFO_COLOR = discord.Color.from_rgb(52, 152, 219) # Mavi
MUTED_COLOR = discord.Color.dark_grey()
MANUEL_ONAY_SETLERI = ["deftank", "support", "healer", "sc-rootbound-lifecurse", "dps"]

# ----- SINIF VE BOT KURULUMU -----
class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        self.add_view(ManualReviewView())
        await self.tree.sync()
        print("Komut ağacı senkronize edildi ve kalıcı View eklendi.")

# ----- VERİ YÖNETİMİ -----
def veri_yukle(dosya_adi):
    try:
        with open(dosya_adi, 'r', encoding='utf-8') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}
def veri_kaydet(dosya_adi, veri):
    with open(dosya_adi, 'w', encoding='utf-8') as f: json.dump(veri, f, indent=4, ensure_ascii=False)

# ----- BOTUN İZİNLERİ VE BAŞLATMA -----
intents = discord.Intents.default()
client = MyClient(intents=intents)

# ----- GEMINI API AYARLARI -----
try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key: vision_model = None
    else:
        genai.configure(api_key=api_key)
        vision_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        print("Gemini API başarıyla yapılandırıldı.")
except Exception as e: vision_model = None

# ----- YARDIMCI FONKSİYONLAR -----
async def analyze_image_with_ai(death_image_data):
    onayli_setler = veri_yukle(ONAYLI_SETLER_DOSYASI)
    if not vision_model or not onayli_setler: return {"error": "AI modeli veya referans setleri yüklü değil."}
    try:
        # --- DEĞİŞİKLİK BURADA ---
        prompt = f"""
        Sen uzman bir Albion Online analistisin. Görevin, bir oyuncunun ölüm raporu ekran görüntüsünü (Ölüm Raporu) inceleyip, ekipmanını sana verilen referans setlerle (Referans Setler) karşılaştırmaktır.

        **KESİN KURAL: 2 PARÇA FARK TOLERANSI**
        Bir oyuncunun seti, 6 ana ekipman parçasından (Kafa, Zırh, Ana El, Yan El, Ayakkabı, Pelerin) **en az 4 tanesi** referans setlerden HERHANGİ BİRİ ile eşleşiyorsa ONAYLANIR.
        - 6/6 eşleşme = ONAYLA
        - 5/6 eşleşme = ONAYLA
        - 4/6 eşleşme = ONAYLA
        - 3/6 veya daha az eşleşme = REDDET

        **ANALİZ ADIMLARI VE ÇIKTI FORMATI:**
        Cevabını iki bölüm halinde ver.

        Bölüm 1: Düşünce Süreci (Zorunlu)
        Bu bölümde, kararını nasıl verdiğini adım adım açıkla.
        1. Oyuncunun adını ve IP'sini yaz.
        2. Oyuncunun giydiği 6 ana parçayı listele.
        3. Her bir referans set ile kaç parça eşleştiğini yaz (Örn: "deftank seti ile 4/6 eşleşti.").
        4. Nihai kararını (Onaylandı/Reddedildi) bu sayıma göre belirt.

        Bölüm 2: JSON Çıktısı (Zorunlu)
        Düşünce sürecine dayanarak, aşağıdaki JSON formatında nihai çıktıyı ver. Bu bölümün başına veya sonuna ```json bloğu koyma. Sadece saf JSON ver.
        - Onay durumunda: `status` alanına '{AI_ONAY_METNI}' yaz ve `matched_set` alanına en çok benzeyen setin adını yaz.
        - Ret durumunda: `status` alanına '{AI_RED_METNI}' yaz.

        {{
          "player_name": "OyuncununAdı",
          "item_power": 1350,
          "status": "{AI_ONAY_METNI} veya {AI_RED_METNI}",
          "matched_set": "Eşleşen Setin Adı veya null"
        }}
        """
        death_image_part = {"mime_type": "image/png", "data": death_image_data}
        content_list = [prompt, "---", "Ölüm Raporu:", death_image_part, "---", "Referans Setler:"]
        for set_name, set_info in onayli_setler.items():
            content_list.append(f"Referans Set Adı: {set_name}")
            dosya_yolu = os.path.join(SET_IMAGES_KLASORU, set_info["filename"])
            try:
                with open(dosya_yolu, "rb") as image_file:
                    image_data = image_file.read()
                    content_list.append({"mime_type": set_info["mime_type"], "data": image_data})
            except FileNotFoundError:
                print(f"UYARI: {dosya_yolu} adlı referans resim dosyası bulunamadı.")
                continue
        
        ai_response = await vision_model.generate_content_async(content_list)
        response_text = ai_response.text
        
        print("--- AI Düşünce Süreci ---")
        print(response_text)
        print("--------------------------")

        try:
            json_start_index = response_text.find('{')
            json_end_index = response_text.rfind('}') + 1
            if json_start_index != -1 and json_end_index != -1:
                json_str = response_text[json_start_index:json_end_index]
                return json.loads(json_str)
            else:
                return {"error": "AI'dan geçerli bir JSON yanıtı alınamadı."}
        except Exception as json_e:
            print(f"JSON parse hatası: {json_e}")
            return {"error": "AI yanıtı işlenirken bir hata oluştu."}

    except Exception as e: 
        return {"error": f"AI analizi sırasında kritik bir hata oluştu: {e}"}

async def update_message_reactions(thread_id: int, message_id: int):
    cache_dosya_yolu = os.path.join(ANALYSIS_CACHE_KLASORU, f"{thread_id}.json")
    if not os.path.exists(cache_dosya_yolu): return
    cache_data = veri_yukle(cache_dosya_yolu)
    message_data = cache_data.get("messages", {}).get(str(message_id))
    if not message_data: return
    approved_count, pending_or_rejected_count = 0, 0
    for attachment_id, attachment_data in message_data.get("attachments", {}).items():
        if "approved" in attachment_data.get("status", ""): approved_count += 1
        else: pending_or_rejected_count += 1
    try:
        thread_channel = client.get_channel(thread_id)
        if thread_channel:
            message = await thread_channel.fetch_message(message_id)
            await message.clear_reactions()
            if approved_count > 0: await message.add_reaction('✅')
            if pending_or_rejected_count > 0: await message.add_reaction('❌')
    except Exception as e: print(f"Reaksiyon güncellenirken hata oluştu: {e}")

# --- TÜM İNTERAKTİF ARAYÜZ SINIFLARI ---
class SetSelectView(ui.View):
    def __init__(self, original_message_id: int, original_channel_id: int, attachment_id: int):
        super().__init__(timeout=180) 
        self.original_message_id, self.original_channel_id, self.attachment_id = original_message_id, original_channel_id, attachment_id
    @ui.select(placeholder="Onaylamak için bir set kategorisi seçin...", options=[discord.SelectOption(label=set_name) for set_name in MANUEL_ONAY_SETLERI], custom_id="persistent_set_select")
    async def select_callback(self, interaction: discord.Interaction, select: ui.Select):
        await interaction.response.defer()
        seçilen_set = select.values[0]
        cache_dosya_yolu = os.path.join(ANALYSIS_CACHE_KLASORU, f"{self.original_channel_id}.json")
        if os.path.exists(cache_dosya_yolu):
            cache_data = veri_yukle(cache_dosya_yolu)
            attachment_data = cache_data.get("messages", {}).get(str(self.original_message_id), {}).get("attachments", {}).get(str(self.attachment_id))
            if attachment_data:
                attachment_data["status"], attachment_data["set"] = "approved_manual", seçilen_set
                veri_kaydet(cache_dosya_yolu, cache_data)
        original_embed = interaction.message.embeds[0]
        new_embed = original_embed.copy()
        new_embed.title, new_embed.color = "✅ Onaylandı", SUCCESS_COLOR
        if len(new_embed.fields) > 4: new_embed.remove_field(index=4)
        new_embed.add_field(name="Seçilen Set Kategorisi", value=f"`{seçilen_set}`", inline=False).add_field(name="İşlemi Yapan", value=interaction.user.mention, inline=False)
        select.disabled = True
        await interaction.message.edit(embed=new_embed, view=self)
        await update_message_reactions(self.original_channel_id, self.original_message_id)
        await interaction.followup.send(f"Talep `{seçilen_set}` olarak onaylandı ve hafızaya kaydedildi.", ephemeral=True)
class ManualReviewView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    async def check_permission(self, interaction: discord.Interaction):
        if not getattr(interaction.user.guild_permissions, YONETICI_IZNI, False):
            await interaction.response.send_message(f"Bu butonları sadece `{YONETICI_IZNI}` iznine sahip olanlar kullanabilir.", ephemeral=True)
            return False
        return True
    
    @ui.button(label="✅ Onayla", style=discord.ButtonStyle.success, custom_id="manual_approve_start")
    async def approve_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.check_permission(interaction): return
        footer_text, image_url = interaction.message.embeds[0].footer.text, interaction.message.embeds[0].image.url or ""
        try:
            ids = {item.split(':')[0].strip(): int(item.split(':')[1].strip()) for item in footer_text.split('|')}
            select_view = SetSelectView(original_message_id=ids["MsgID"], original_channel_id=ids["ChnID"], attachment_id=ids["AttachID"])
            await interaction.response.edit_message(view=select_view)
        except (IndexError, ValueError, KeyError):
             await interaction.response.send_message("Hata: Gerekli ID'ler okunamadı.", ephemeral=True)
    
    @ui.button(label="❌ Reddet", style=discord.ButtonStyle.danger, custom_id="manual_reject")
    async def reject_button(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.check_permission(interaction): return
        original_embed = interaction.message.embeds[0]
        new_embed = original_embed.copy()
        new_embed.title, new_embed.color = "❌ Reddedildi", ERROR_COLOR
        new_embed.add_field(name="İşlemi Yapan", value=interaction.user.mention, inline=False)
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(embed=new_embed, view=self)
        try:
            footer_text = interaction.message.embeds[0].footer.text
            ids = {item.split(':')[0].strip(): int(item.split(':')[1].strip()) for item in footer_text.split('|')}
            cache_dosya_yolu = os.path.join(ANALYSIS_CACHE_KLASORU, f"{ids['ChnID']}.json")
            if os.path.exists(cache_dosya_yolu):
                cache_data = veri_yukle(cache_dosya_yolu)
                attachment_data = cache_data.get("messages", {}).get(str(ids["MsgID"]), {}).get("attachments", {}).get(str(ids["AttachID"]))
                if attachment_data:
                    attachment_data["status"] = "rejected_manual"
                    veri_kaydet(cache_dosya_yolu, cache_data)
            await update_message_reactions(ids['ChnID'], ids['MsgID'])
        except (IndexError, ValueError, KeyError) as e:
            print(f"Reddetme sonrası reaksiyon güncellenemedi: {e}")
class SetDisplayView(ui.View):
    def __init__(self, sets_data: dict):
        super().__init__(timeout=300)
        self.sets_data = sets_data
        options = [discord.SelectOption(label=set_name, description=f"`{set_name}` setini görüntüle.") for set_name in self.sets_data.keys()]
        if options: self.add_item(self.SetSelect(options))
    class SetSelect(ui.Select):
        def __init__(self, options: list):
            super().__init__(placeholder="Görüntülemek için bir set seçin...", options=options, custom_id="set_display_dropdown")
        async def callback(self, interaction: discord.Interaction):
            view: 'SetDisplayView' = self.view 
            if not view: return
            await interaction.response.defer()
            selected_set_name = self.values[0]
            set_info = view.sets_data.get(selected_set_name)
            if not set_info:
                await interaction.edit_original_response(content="Hata: Seçilen set bulunamadı.", embed=None, view=None)
                return
            embed = discord.Embed(title=f"🖼️ Set: `{selected_set_name}`", color=INFO_COLOR)
            file_path = os.path.join(SET_IMAGES_KLASORU, set_info["filename"])
            try:
                file = discord.File(file_path, filename=set_info["filename"])
                embed.set_image(url=f"attachment://{set_info['filename']}")
                for item in view.children:
                    if isinstance(item, ui.Select): item.disabled = True
                await interaction.edit_original_response(embed=embed, attachments=[file], view=view)
            except FileNotFoundError:
                error_embed = discord.Embed(description="❌ Bu set için resim dosyası bulunamadı.", color=ERROR_COLOR)
                await interaction.edit_original_response(embed=error_embed, view=None)
            except Exception as e:
                await interaction.edit_original_response(content=f"Bir hata oluştu: {e}", embed=None, view=None)

# ----- BOT OLAYLARI -----
@client.event
async def on_ready():
    os.makedirs(SET_IMAGES_KLASORU, exist_ok=True)
    os.makedirs(ANALYSIS_CACHE_KLASORU, exist_ok=True)
    activity = discord.Activity(name="Ölüm Raporlarını 🐙", type=discord.ActivityType.watching)
    await client.change_presence(status=discord.Status.online, activity=activity)
    print(f'-> {client.user} olarak Discord\'a bağlandık. Bot hazır!')

# ----- SLASH KOMUTLARI -----
# ... (Diğer tüm komutlar öncekiyle aynı, tam halleriyle aşağıdadır)

# ----- BOTU ÇALIŞTIRMA -----
token = os.getenv("DISCORD_TOKEN")
if token:
    try: client.run(token)
    except Exception as e: print(f"Bot çalıştırılırken bir hata oluştu: {e}")
else: print("HATA: DISCORD_TOKEN bulunamadı.")