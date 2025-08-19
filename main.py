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
    if not api_key:
        vision_model = None
        print("UYARI: GEMINI_API_KEY bulunamadı.")
    else:
        genai.configure(api_key=api_key)
        vision_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        print("Gemini API başarıyla yapılandırıldı.")
except Exception as e:
    vision_model = None
    print(f"UYARI: Gemini API yapılandırılamadı. Hata: {e}")

# ----- YARDIMCI FONKSİYONLAR -----
async def analyze_image_with_ai(death_image_data):
    onayli_setler = veri_yukle(ONAYLI_SETLER_DOSYASI)
    if not vision_model or not onayli_setler: return {"error": "AI modeli veya referans setleri yüklü değil."}
    try:
        prompt = f"""
        Sen dikkatli ve metodik bir Albion Online veri analistisin. Resimlerin kalitesi düşük veya itemler belirsiz olabilir, yine de en iyi tahminini yapmalısın.

        **ADIM 1: VERİ ÇIKARMA (ZORUNLU)**
        Öncelikle, resimden aşağıdaki bilgileri dikkatlice bul ve çıkar:
        - `player_name`: Ölen oyuncunun adı. Genellikle solda ve büyük yazılır.
        - `item_power`: Oyuncunun "Average Item Power" değeri. Bu bir sayıdır. **Eğer bu sayıyı resimde kesinlikle bulamıyorsan, bu alana `0` yaz.**

        **ADIM 2: EKİPMAN ANALİZİ**
        Şimdi, çıkardığın bilgilere dayanarak ekipman analizini yap.
        - **KESİN KURAL: 2 PARÇA FARK TOLERANSI**
          - Oyuncunun 6 ana ekipmanını (Kafa, Zırh, Ayakkabı, Ana El, Yan El, Pelerin) referans setlerle karşılaştır.
          - Eğer eşleşen parça sayısı **4, 5, veya 6** ise, sonuç ONAYDIR (`{AI_ONAY_METNI}`).
          - Eğer eşleşen parça sayısı **3 veya daha az** ise, sonuç RETTİR (`{AI_RED_METNI}`).
        - Kozmetik farkları (seviye, kalite vb.) görmezden gel.

        **ADIM 3: ÇIKTI OLUŞTURMA**
        Tüm analizini, başka hiçbir metin veya açıklama olmadan, SADECE aşağıdaki JSON formatında ver.

        {{
          "player_name": "OyuncununAdı",
          "item_power": 1473,
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
        
        print(f"AI Ham Cevabı: {response_text}")

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
@client.tree.command(name="yardım", description="Botun komutları ve işleyişi hakkında bilgi verir.")
async def yardim(interaction: discord.Interaction):
    embed = discord.Embed(title="🐙 Palegrin Regear Asistanı Yardım Menüsü", description="Merhaba! Ben Palegrin Guild'inin regear sürecini otomatize etmek ve yönetmek için buradayım.", color=INFO_COLOR)
    embed.set_thumbnail(url=client.user.avatar.url if client.user.avatar else None)
    embed.add_field(name="📝 Yeni Regear İş Akışı", value="1. **Analiz Başlat:** Bir yönetici, regear taleplerinin olduğu konuya `/analiz-et` komutunu yazar. Bu, o konu için özel bir **analiz oturumu (hafıza)** başlatır.\n2. **Otomatik Değerlendirme:** Bot, tüm resimleri tarar ve sonuçları hafızaya kaydeder. İlk değerlendirmeye göre mesajlara ✅/❌ tepkilerini koyar. Manuel onay gerekenler, ilgili kanala butonlarla raporlanır.\n3. **Manuel Onay:** Yöneticiler, `#manuel-onay` kanalındaki talepleri butonları kullanarak yönetir. Verilen her karar, hafızaya anında işlenir ve orijinal mesajdaki tepkiler **dinamik olarak güncellenir.**\n4. **Listeleme ve Oturumu Kapatma:** Süreç bittiğinde, yönetici `/liste-olustur` ile nihai ödeme listesini alır. Liste gönderildikten sonra **o oturumun hafızası temizlenir** ve süreç tamamlanır.", inline=False)
    embed.add_field(name="🛠️ Yönetici Komutları", value="`/analiz-et`: Bir analiz oturumu başlatır.\n`/liste-olustur`: Mevcut oturumdaki onaylanmış talepleri listeler.\n`/set-resmi-ekle`: Yeni bir referans set ekler.\n`/set-sil`: Bir referans setini siler.\n`/setleri-goster`: Kayıtlı tüm setleri interaktif olarak gösterir.", inline=False)
    embed.set_footer(text="Palegrin Guild'i için özel olarak geliştirildi.")
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
@client.tree.command(name="set-resmi-ekle", description="Onaylı bir regear setini resim olarak tanımlar.")
async def set_resmi_ekle(interaction: discord.Interaction, set_adi: str, resim: discord.Attachment):
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        set_adi = set_adi.lower().strip().replace(" ", "_")
        dosya_adi = f"{set_adi}.png"
        dosya_yolu = os.path.join(SET_IMAGES_KLASORU, dosya_adi)
        await resim.save(dosya_yolu)
        onayli_setler = veri_yukle(ONAYLI_SETLER_DOSYASI)
        onayli_setler[set_adi] = {"filename": dosya_adi, "mime_type": resim.content_type}
        veri_kaydet(ONAYLI_SETLER_DOSYASI, onayli_setler)
        embed = discord.Embed(title="✅ Set Kaydedildi", description=f"`{set_adi}` adlı set başarıyla veritabanına eklendi.", color=SUCCESS_COLOR)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(title="❌ İşlem Başarısız", description=f"Set kaydedilirken bir hata oluştu:\n`{e}`", color=ERROR_COLOR)
        await interaction.followup.send(embed=embed)

@client.tree.command(name="set-sil", description="Tanımlı bir set resmini siler.")
async def set_sil(interaction: discord.Interaction, set_adi: str):
    await interaction.response.defer(thinking=True, ephemeral=True)
    set_adi = set_adi.lower().strip()
    onayli_setler = veri_yukle(ONAYLI_SETLER_DOSYASI)
    if set_adi in onayli_setler:
        set_bilgisi = onayli_setler[set_adi]
        if "filename" in set_bilgisi:
            try:
                dosya_yolu = os.path.join(SET_IMAGES_KLASORU, set_bilgisi["filename"])
                if os.path.exists(dosya_yolu): os.remove(dosya_yolu)
            except Exception as e:
                await interaction.followup.send(embed=discord.Embed(title="❌ Hata", description=f"Resim dosyası silinirken hata oluştu: {e}", color=ERROR_COLOR))
                return
        del onayli_setler[set_adi]
        veri_kaydet(ONAYLI_SETLER_DOSYASI, onayli_setler)
        await interaction.followup.send(embed=discord.Embed(title="🗑️ Set Silindi", description=f"`{set_adi}` adlı set başarıyla silindi.", color=SUCCESS_COLOR))
    else:
        await interaction.followup.send(embed=discord.Embed(title="⚠️ Bulunamadı", description=f"`{set_adi}` adında bir set bulunamadı.", color=WARN_COLOR))

@client.tree.command(name="setleri-goster", description="Kaydedilmiş tüm onaylı regear setlerini interaktif olarak listeler.")
async def setleri_goster(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    current_sets = veri_yukle(ONAYLI_SETLER_DOSYASI)
    if not current_sets:
        await interaction.followup.send(embed=discord.Embed(title="ℹ️ Bilgi", description="Henüz kaydedilmiş bir regear seti bulunmuyor.", color=INFO_COLOR))
        return
    initial_embed = discord.Embed(title="💾 Kayıtlı Regear Setleri", description="Görüntülemek için aşağıdaki menüden bir set seçin.", color=INFO_COLOR)
    view = SetDisplayView(sets_data=current_sets)
    await interaction.followup.send(embed=initial_embed, view=view)

@client.tree.command(name="analiz-et", description="Bu konudaki regear taleplerini analiz eder ve bir hafıza oturumu başlatır.")
async def analiz_et(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.Thread):
        await interaction.response.send_message(embed=discord.Embed(title="❌ Hatalı Komut Kullanımı", description="Bu komut sadece bir **konu (thread)** içinde kullanılabilir.", color=ERROR_COLOR), ephemeral=True)
        return
    await interaction.response.defer(thinking=True, ephemeral=True)
    
    cache_dosya_yolu = os.path.join(ANALYSIS_CACHE_KLASORU, f"{interaction.channel.id}.json")
    cache_data = {"messages": {}}
    
    manuel_kanali = client.get_channel(MANUEL_ONAY_KANAL_ID)
    if not manuel_kanali:
        await interaction.followup.send(embed=discord.Embed(title="❌ Kurulum Hatası", description="Manuel onay kanalı bulunamadı.", color=ERROR_COLOR), ephemeral=True)
        return
        
    await interaction.followup.send(embed=discord.Embed(title="🐙 Hafıza Çekirdekleri Aktif!", description=f"`{interaction.channel.name}` konusundaki resimler taranıyor...", color=INFO_COLOR), ephemeral=True)
    
    toplam_otomatik_onay, toplam_manuel_ret = 0, 0
    async for message in interaction.channel.history(limit=200, oldest_first=True):
        if message.author.bot or not message.attachments: continue
        
        await message.clear_reactions()
        cache_data["messages"][str(message.id)] = {"attachments": {}}
        
        for attachment in message.attachments:
            if not (attachment.content_type and attachment.content_type.startswith('image/')): continue
            try:
                image_data = await attachment.read()
                result = await analyze_image_with_ai(image_data)
                
                player_name_raw = result.get("player_name")
                oyuncu_adi = player_name_raw.strip() if isinstance(player_name_raw, str) and player_name_raw.strip() else "isim okunamadı"
                set_adi = result.get("matched_set")
                
                ip = result.get("item_power") or 0
                
                attachment_cache = {"player": oyuncu_adi, "set": set_adi, "ip": ip, "discord": message.author.display_name}

                if not result.get("error") and ip >= MINIMUM_IP and result.get("status") == AI_ONAY_METNI:
                    attachment_cache["status"] = "approved_auto"
                else:
                    attachment_cache["status"] = "pending_manual"
                    reason_title, reason_desc, embed_color = "🧐 Ahtapotun Gözünden Kaçan Bir Detay", "AI, seti referans setlerle eşleştiremedi.", WARN_COLOR
                    
                    ai_error_msg = result.get('error')
                    if ai_error_msg:
                        reason_title, reason_desc = "❗ AI Analiz Hatası", f"`{ai_error_msg[:900]}`"
                    elif ip < MINIMUM_IP:
                        reason_title, reason_desc, embed_color = "⛔ Regear Reddedildi", f"Düşük IP: `{ip}` (Min: `{MINIMUM_IP}`)", ERROR_COLOR
                    
                    manual_embed = discord.Embed(title=f"{reason_title}", color=embed_color, timestamp=datetime.now())
                    manual_embed.add_field(name="Oyuncu", value=f"`{oyuncu_adi}`", inline=True).add_field(name="Talebi Yapan", value=message.author.mention, inline=True)
                    manual_embed.add_field(name="Kaynak Konu", value=f"[{interaction.channel.name}]({interaction.channel.jump_url})", inline=False).add_field(name="Sebep", value=reason_desc, inline=False)
                    manual_embed.set_image(url=f"attachment://{attachment.filename}")
                    manual_embed.set_footer(text=f"MsgID: {message.id} | ChnID: {interaction.channel.id} | AttachID: {attachment.id}")
                    file = discord.File(io.BytesIO(image_data), filename=attachment.filename)
                    await manuel_kanali.send(embed=manual_embed, file=file, view=ManualReviewView())

                cache_data["messages"][str(message.id)]["attachments"][str(attachment.id)] = attachment_cache
            except Exception as e:
                print(f"Analiz döngüsünde hata (Mesaj ID: {message.id}): {e}")
                try: await message.add_reaction('⚠️')
                except: pass
        
        veri_kaydet(cache_dosya_yolu, cache_data)
        await update_message_reactions(interaction.channel.id, message.id)
        
    final_cache = veri_yukle(cache_dosya_yolu)
    for msg_data in final_cache.get("messages", {}).values():
        for attach_data in msg_data.get("attachments", {}).values():
            if attach_data.get("status") == "approved_auto": toplam_otomatik_onay += 1
            elif attach_data.get("status") == "pending_manual": toplam_manuel_ret += 1
            
    summary_embed = discord.Embed(title="📜 Analiz Raporu Hazır", description=f"`{interaction.channel.name}` konusundaki tarama tamamlandı ve sonuçlar hafızaya kaydedildi.", color=INFO_COLOR)
    summary_embed.add_field(name="✅ Otomatik Onaylanan", value=f"**{toplam_otomatik_onay}** adet", inline=True)
    summary_embed.add_field(name="❓ Manuel Onay Bekleyen", value=f"**{toplam_manuel_ret}** adet", inline=True)
    summary_embed.set_footer(text=f"Yöneticilerin manuel onayları tamamlamasının ardından /liste-olustur komutunu kullanın.")
    await interaction.channel.send(embed=summary_embed)

@client.tree.command(name="liste-olustur", description="Mevcut analiz oturumundaki onaylanmış regear'ları listeler.")
@app_commands.default_permissions(manage_guild=True)
async def liste_olustur(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.Thread):
        await interaction.response.send_message("Bu komut sadece bir konu (thread) içinde kullanılabilir.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True, ephemeral=True)
    
    cache_dosya_yolu = os.path.join(ANALYSIS_CACHE_KLASORU, f"{interaction.channel.id}.json")
    if not os.path.exists(cache_dosya_yolu):
        await interaction.followup.send(embed=discord.Embed(title="⚠️ Hafıza Bulunamadı", description="Bu konu için başlatılmış bir analiz oturumu bulunamadı. Lütfen önce `/analiz-et` komutunu çalıştırın.", color=WARN_COLOR), ephemeral=True)
        return

    cache_data = veri_yukle(cache_dosya_yolu)
    lines = []

    for msg_id, msg_data in cache_data.get("messages", {}).items():
        for attach_id, attach_data in msg_data.get("attachments", {}).items():
            status = attach_data.get("status", "")
            if "approved" in status:
                discord_name = attach_data.get("discord") or "Bilinmiyor"
                set_name = attach_data.get("set") or "set tespit edilemedi"
                if status == "approved_manual":
                    line = f"{discord_name} - {set_name} - manuel olarak onaylanmıştır"
                else:
                    player_name = attach_data.get("player") or "isim okunamadı"
                    line = f"{discord_name} - {player_name} - {set_name}"
                lines.append(line)

    if not lines:
        await interaction.followup.send(embed=discord.Embed(title="ℹ️ Bilgi", description="Hafızada listelenecek onaylanmış bir talep bulunamadı.", color=INFO_COLOR), ephemeral=True)
        return
    
    final_list = sorted(lines)
    file_content = "\n".join(final_list)
    buffer = io.BytesIO(file_content.encode('utf-8'))
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    file = discord.File(buffer, filename=f"onay_listesi_{interaction.channel.name.replace(' ', '_')}_{timestamp}.txt")

    embed=discord.Embed(title="✒️ Onay Listesi Mürekkeple Damgalandı!", description=f"`{interaction.channel.name}` konusu için **{len(final_list)}** onaylanmış talep bulundu.", color=SUCCESS_COLOR)
    await interaction.channel.send(content=f"Hey {interaction.user.mention}!", embed=embed, file=file)
    
    try:
        buffer.seek(0)
        dm_file = discord.File(buffer, filename=f"onay_listesi_{interaction.channel.name.replace(' ', '_')}_{timestamp}.txt")
        await interaction.user.send(f"`{interaction.channel.name}` konusu için oluşturulan onay listesi:", file=dm_file)
    except discord.Forbidden:
        await interaction.followup.send("Sana özel mesaj gönderemedim, DM'lerin kapalı olabilir.", ephemeral=True)
    
    await interaction.followup.send("Liste başarıyla oluşturuldu ve analiz hafızası temizlendi.", ephemeral=True)
    
    try:
        os.remove(cache_dosya_yolu)
        print(f"Hafıza dosyası ({cache_dosya_yolu}) başarıyla silindi.")
    except Exception as e:
        print(f"Hafıza dosyası silinirken bir hata oluştu: {e}")

# ----- BOTU ÇALIŞTIRMA -----
token = os.getenv("DISCORD_TOKEN")
if token:
    try: client.run(token)
    except Exception as e: print(f"Bot çalıştırılırken bir hata oluştu: {e}")
else: print("HATA: DISCORD_TOKEN bulunamadı.")