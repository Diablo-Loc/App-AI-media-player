"""Universal ASR-to-Reference Lyric Snapping (Whisper Timing + Official Reference Wording).

When a song goes through Whisper ASR (covers, live performances, medleys, dramatic story MVs,
tempo-altered edits, or tracks without synced LRC), Whisper owns 100% of cue start/end timestamps
while this module upgrades matching cue text to official reference lyrics (e.g. LRCLIB plainLyrics)
using global monotonic dynamic programming and script/phonetic normalization.

Guarantees:
- Cue `start` and `end` timestamps are NEVER mutated by a single millisecond.
- Handles 1:1 lines, 1:2 / 1:3 merged ASR cues, and 2:1 split ASR cues cleanly.
- Cross-script / phonetic normalization supports Japanese (Katakana<->Hiragana + Kanji overlap),
  Chinese (Traditional<->Simplified folding + sandwich homophone rescue), Korean (Hangul Jamo NFD
  liaison tolerance), Vietnamese, and English/Latin.
- Multi-candidate selection automatically picks the true song (e.g. 'Run' vs 'Run BTS') and
  rejects wrong-song candidates completely.
- Medley / partial-song mode snaps only high-precision lines (>=0.76) while leaving other songs
  or spoken MV dialogue untouched.
"""
from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any, Iterable, Optional

from pipeline.lyric_accuracy import credit_text

_LRC_TS_RE = re.compile(r"\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]")
_INLINE_TS_RE = re.compile(r"<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>")
_SECTION_HEADER_RE = re.compile(r"^\s*\[[^\]]{1,80}\]\s*$")
_INSTRUMENTAL_RE = re.compile(
    r"^(?:[\[(]?\s*(?:instrumental|music|interlude|outro|intro|solo|guitar solo|piano solo|"
    r"間奏|前奏|後奏|伴奏|纯音乐|純音樂)\s*[\])]?)$",
    re.IGNORECASE,
)
_SYMBOL_ONLY_RE = re.compile(r"^[\s♪♫♬🎵🎶♩♭♯•·.\-~—_=*()\[\]【】「」『』]+$")
_TRAILING_ADLIB_PAREN_RE = re.compile(
    r"\s*[\[(（](?:ooh+|oh+|ah+|uh+|yeah+|yea+|woah+|whoa+|la+|na+|mm+|hm+|ha+|hey+)[\])）]\s*$",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")

# Compact high-frequency Traditional -> Simplified Chinese map for lyric matching
_ZH_TRAD = (
    "風雲夢愛戀淚聲聽見覺記語說誰讓認識變離開關門間閃電霧靜響頁頭顆顏願飛餘馬驚髮鳥麗點齊龍"
    "會處跡暈傘著溫熱臟進該樣輕尋這裡後發臉邊過還時長東車魚個們來倫傷傾僅價優償億儘兒兩興舉舊"
    "葉號嘆單喬喪嚴囑國圖圓壓場塊壞堅塵墜墮壇壽夠奪奮妝婦嫋學寧寶實審寫寬寵導對專屆層歲島嶺"
    "嶼巔帶幀幫幾廣廢應懷態憐慮慶憂憑憶憾懶懼戲戰戶擁擇擔據擠擬擱擺擾敗數斂斷於晝暉暫書殺雜"
    "權條楊楓構槍橋機橫檔檢欄櫻歡歎歐欽殘殞殼毀氣決沒沖況泄淚瀉潑澤潔潛潤潰澆澈澗瀾灑灘滅燈"
    "靈災燦爐烏煙煩燒燙燼熾燄獨獵獸獻猶瑣瑤瑩瑪環璽瓊甦產畫異當疆療癡瘋瘡皺盜盞監盤盧盪眾睜"
    "睞瞞瞭瞰瞼矚矯磚碗碩確碼礎礙礦礪礫禱禍祿禪禮種稱稅穩穫積穎穗穢竊竅竇競篤筆筍箏算箋節範"
    "築篩篷簇簍簡簫簷簽簾籃籌籍籠籬籮粵糧粹糊縣縫縮縱縷總績繁繃繆織繕繚繞繡繪繩繼繽續纏纓纖"
    "纜佇淚靨佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇佇"
    "萬與專業叢絲丟並嚴個豐臨為舉麼義烏樂喬習鄉書買亂乾了予爭事二于虧云互五井亞些亡交亥亦產"
    "享京亭亮親人仁什僅今介仍從侖倉仔仕他仗付仙仝仞仟代令以儀們仰仲件價任份仿企伊伍伎伏伐休"
    "優伙偉傳伛傘偉傳傷傯倫傴偽佇體餘佛作佞佟你傭佩佳併佶佻佼使侃來侈例侍侏侑侖侗侘供依俠侶"
    "僥偵側僑膾儕儂盡侯侵侶局卻即歷隻動務勝勞勢勤勵勸勻匂匆包匈匍匏匕化北匙匝匠匡匣匪匱匹區"
    "醫匾匿十千卅升午卉半卑卒卓協南博卜卞占卡盧卣卦臥衛印危即卻卵卷卸卹卻卿廠厄廳歷厲壓厭厙"
    "廁廂厤廈廚廄廝去縣參又叉及友雙反發叔取受變敘叛叟疊口古句另叨叩只叫召叭叮可台叱史右叵叶"
    "司嘆叻叼嘰吁吃各吆合吉吊同名后吏吐向吒嚇呂吖嗎君吝吞吟吠吡吣否吧噸吩含聽吭吮啟吱吲吳吵"
    "吸吹吻吼吾呀呂呃呆呈告呋呎呇呐呒呓呔呕呖呗员呙呛呜呢呣呤呦周呱呲味呵呶呷呸呻呼命咀咁咂"
    "咄咆咋和咎咏咐咒咔咕咖咙咚咛咝咣咤咦咧咨咩咪咫咬咭咯咱咳咴咸咻咽咿哀品哂哄哆哇哈哉哌响"
    "哎哏哐哑哓哔哕哗哙哚哜哝哞哟哥哦哧哨哩哪哭哮哲哳哺哼哽哿唁唆唇唉唏唐唑唔唛唠唢唣唤唧唪"
    "唬售唯唱唳唷唼唾唿啁啃啄商啉啊啐啕啖啜啡啤啥啦啧啪啬啭啮啰啱啲啵啶啷啸啻啼啾喀喁喂喃善"
    "喆喇喈喉喊喋喏喑喔喘喙喜喝喟喧喱喳喵喷喹喻喽喾嗄嗅嗉嗌嗍嗑嗒嗓嗔嗖呜嗜嗝嗟嗡嗣嗤嗥嗦嗨"
    "嗪嗫嗬嗯嗲嗳嗵哔嗷嗽嗾嘀嘁嘈嘉嘌嘎嘏嘘嘛嘞嘟嘣嘤嘧嘬嘭嘱嘲嘴嘶嘹嘻嘿噌噍噎嘘噔噗噘噙噜"
    "噢噤器噩噪噫噬噱噶噻噼嚅嚓嚣嚷嚼囊囍囑囚四回因團囤園困囱围囵囷囹固国图囿圃圄圆圈圉圊国"
    "土圣在圩圪圬圭圮圯地圳圹场圻圾址坂均坊坌坍坎坏坐坑块坚坛坜坝坞坟坠坡坤坦坨坩坪坫坭坯坳"
    "坷坻坼垂垃垄垆型垌垒垓垛垠垡垢垣垤垦垧垩垫垭垮垲垴垸埂埃埋城埏埒埔埕埘埙埚埝域埠埤埭埯"
    "埴埸培基埽崎堁堂堃堆堇堊堝堟堠堡堤堪堯堰報場堵堺堽塊塋塌塍塑塒塔塗塘塚塞塢塤填塵塹塾墀"
    "墁境墅墉墊墑墒墓牆墚墜增墟墨墩墮墳墼墾壁壅壇壑壓壕壘壙廬壞壟壠壢壤士壬壯聲殼壺壹處備復"
    "夏夕外夙多夜夠夢夥大天太夫夭央夯失頭夷夸夾奪奩奐契奔奕獎套奘奚奠奢奧奪奼奸她好如妃妄妊"
)
_ZH_SIMP = (
    "风云梦爱恋泪声听见觉记语说谁让认识变离开关门间闪电雾静响页头颗颜愿飞余马惊发鸟丽点齐龙"
    "会处迹晕伞着温热脏进该样轻寻这里后发脸边过还时长东车鱼个们来伦伤倾仅价优偿亿尽儿两兴举旧"
    "叶号叹单乔丧严嘱国图圆压场块坏坚尘坠堕坛寿够夺奋妆妇袅学宁宝实审写宽宠导对专届层岁岛岭"
    "屿巅带帧帮几广废应怀态怜虑庆忧凭忆憾懒惧戏战户拥择担据挤拟搁摆扰败数敛断于昼晖暂书杀杂"
    "权条杨枫构枪桥机横档检栏樱欢叹欧钦残殒壳毁气决没冲况泄泪泻泼泽洁潜润溃浇澈涧澜洒滩灭灯"
    "灵灾灿炉乌烟烦烧烫烬炽焰独猎兽献犹琐瑶莹玛环玺琼苏产画异当疆疗痴疯疮皱盗盏监盘卢荡众睁"
    "睐瞒了瞰睑瞩矫砖碗硕确码础碍矿砺砾祷祸禄禅礼种称税稳获积颖穂秽窃窍窦竞笃笔笋筝算笺节范"
    "筑筛篷簇篓简箫檐签帘篮筹籍笼篱箩粤粮粹糊县缝缩纵缕总绩繁绷缪织缮缭绕绣绘绳继缤续缠缨纤"
    "缆伫泪靥伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫伫"
    "万与专业丛丝丢并严个丰临为举么义乌乐乔习乡书买乱干了予争事二于亏云互五井亚些亡交亥亦产"
    "享京亭亮亲人仁什仅今介仍从仑仓仔仕他仗付仙仝仞仟代令以仪们仰仲件价任份仿企伊伍伎伏伐休"
    "优伙伟传伛伞伟传伤傯伦偻伪伫体余佛作佞佟你佣佩佳并佶佻佼使侃来侈例侍侏侑仑侗侘供依侠侣"
    "侥侦侧侨脍侪侬尽侯侵侣局却即历只动务胜劳势勤励劝匀匂匆包匈匍匏匕化北匙匝匠匡匣匪匮匹区"
    "医匾匿十千卅升午卉半卑卒卓协南博卜卞占卡卢卣卦卧卫印危即却卵卷卸恤却卿厂厄厅历厉压厌厍"
    "厕厢历厦厨厩厮去县参又叉及友双反发叔取受变叙叛叟叠口古句另叨叩只叫召叭叮可台叱史右叵叶"
    "司叹叻叼叽吁吃各吆合吉吊同名后吏吐向吒吓吕吖吗君吝吞吟吠吡吣否吧吨吩含听吭吮启吱吲吴吵"
    "吸吹吻吼吾呀吕呃呆呈告呋尺呇呐呒呓呔呕呖呗员呙呛呜呢呣呤呦周呱呲味呵呶呷呸呻呼命咀咁咂"
    "咄咆咋和咎咏咐咒咔咕咖咙咚咛咝咣咤咦咧咨咩咪咫咬咭咯咱咳咴咸咻咽咿哀品哂哄哆哇哈哉哌响"
    "哎哏哐哑哓哔哕哗哙哚哜哝哞哟哥哦哧哨哩哪哭哮哲哳哺哼哽哿唁唆唇唉唏唐唑唔唛唠唢唣唤唧唪"
    "唬售唯唱唳唷唼唾唿啁啃啄商啉啊啐啕啖啜啡啤啥啦啧啪啬啭啮啰啱啲啵啶啷啸啻啼啾喀喁喂喃善"
    "喆喇喈喉喊喋喏喑喔喘喙喜喝喟喧喱喳喵喷喹喻喽喾嗄嗅嗉嗌嗍嗑嗒嗓嗔嗖呜嗜嗝嗟嗡嗣嗤嗥嗦嗨"
    "嗪嗫嗬嗯嗲嗳嗵哔嗷嗽嗾嘀嘁嘈嘉嘌嘎嘏嘘嘛嘞嘟嘣嘤嘧嘬嘭嘱嘲嘴嘶嘹嘻嘿噌噍噎嘘噔噗噘噙噜"
    "噢噤器噩噪噫噬噱噶噻噼嚅嚓嚣嚷嚼囊囍嘱囚四回因团囤园困囱围囵囷囹固国图囿圃圄圆圈圉圊国"
    "土圣在圩圪圬圭圮圯地圳圹场圻圾址坂均坊坌坍坎坏坐坑块坚坛坜坝坞坟坠坡坤坦坨坩坪坫坭坯坳"
    "坷坻坼垂垃垄垆型垌垒垓垛垠垡垢垣垤垦垧垩垫垭垮垲垴垸埂埃埋城埏埒埔埕埘埙埚埝域埠埤埭埯"
    "埴埸培基埽崎堁堂堃堆堇垩埚堟堠堡堤堪尧堰报场堵堺堽块茔塌塍塑埘塔涂塘冢塞坞埙填尘堑塾墀"
    "墁境墅墉垫墒墒墓墙墚坠增墟墨墩堕坟墼垦壁壅坛壑压壕垒圹庐坏垄断坜壤士壬壮声壳壶壹处备复"
    "夏夕外夙多夜够梦伙大天太夫夭央夯失头夷夸夹夺奁奂契奔奕奖套奘奚奠奢奥夺姹奸她好如妃妄妊"
)
assert len(_ZH_TRAD) == len(_ZH_SIMP)
_ZH_TABLE = str.maketrans(_ZH_TRAD, _ZH_SIMP)


def _katakana_to_hiragana(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def normalize_lyric_key(text: str, lang: str = "") -> str:
    """Script- and phonetic-aware normalization for comparing ASR text against official lyrics."""
    raw = unicodedata.normalize("NFKC", str(text or "")).casefold()
    raw = raw.translate(_ZH_TABLE)
    raw = _katakana_to_hiragana(raw)
    lang_code = str(lang or "").lower()[:2]
    # Decompose Hangul syllables into Jamo so Korean liaison/assimilation differences stay >80% similar
    out_chars: list[str] = []
    for ch in raw:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            out_chars.append(unicodedata.normalize("NFD", ch))
        elif ch.isalnum() or (lang_code == "ja" and ch == "ー"):
            out_chars.append(ch)
    return "".join(out_chars)


def extract_reference_lines(lyrics: str) -> list[str]:
    """Clean raw plainLyrics or syncedLyrics into ordered lyric lines without headers/credits."""
    text = unicodedata.normalize("NFKC", str(lyrics or "")).replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = _LRC_TS_RE.sub("", raw_line)
        line = _INLINE_TS_RE.sub("", line)
        line = _SPACE_RE.sub(" ", line).strip()
        if not line:
            continue
        if _SECTION_HEADER_RE.fullmatch(line) or _INSTRUMENTAL_RE.fullmatch(line) or _SYMBOL_ONLY_RE.fullmatch(line):
            continue
        if credit_text(line, timed_words=False):
            continue
        if len(normalize_lyric_key(line)) < 1:
            continue
        lines.append(line)
    return lines


def _char_ngrams(text: str, size: int = 2) -> Counter:
    if not text:
        return Counter()
    if len(text) < size:
        return Counter({text: 1})
    return Counter(text[i : i + size] for i in range(len(text) - size + 1))


def _has_cjk_ideographs(text: str) -> bool:
    return any(0x4E00 <= ord(ch) <= 0x9FFF for ch in text)


def _key_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    len_a, len_b = len(a), len(b)
    length_fit = min(len_a, len_b) / float(max(len_a, len_b))
    if length_fit < 0.32:
        return 0.0
    ratio = SequenceMatcher(None, a, b, autojunk=False).ratio()
    ga2 = _char_ngrams(a, 2 if min(len_a, len_b) >= 4 else 1)
    gb2 = _char_ngrams(b, 2 if min(len_a, len_b) >= 4 else 1)
    tot2 = sum(ga2.values())
    cov2 = (sum((ga2 & gb2).values()) / float(tot2)) if tot2 else 0.0
    if _has_cjk_ideographs(a) or _has_cjk_ideographs(b):
        ga1 = _char_ngrams(a, 1)
        gb1 = _char_ngrams(b, 1)
        tot1 = sum(ga1.values())
        cov1 = (sum((ga1 & gb1).values()) / float(tot1)) if tot1 else 0.0
        cov = 0.55 * cov2 + 0.45 * cov1
    else:
        cov = cov2
    return 0.52 * ratio + 0.36 * cov + 0.12 * length_fit


def _harmonize_adlib_tail(asr_text: str, ref_text: str, lang: str = "") -> str:
    """Strip unsung trailing '(ooh)'/'(yeah)' from reference line only when ASR clearly omitted it."""
    stripped = _TRAILING_ADLIB_PAREN_RE.sub("", ref_text).strip()
    if not stripped or stripped == ref_text:
        return ref_text
    ka = normalize_lyric_key(asr_text, lang)
    k_full = normalize_lyric_key(ref_text, lang)
    k_strip = normalize_lyric_key(stripped, lang)
    if _key_similarity(ka, k_strip) >= _key_similarity(ka, k_full) + 0.07:
        return stripped
    return ref_text


def _split_reference_for_two_cues(
    ref_line: str,
    asr_first: str,
    asr_second: str,
    lang: str = "",
) -> Optional[tuple[str, str]]:
    """Split one reference line across two split ASR cues at the cleanest word/clause boundary."""
    text = _SPACE_RE.sub(" ", ref_line).strip()
    if len(text) < 4:
        return None
    k1 = normalize_lyric_key(asr_first, lang)
    k2 = normalize_lyric_key(asr_second, lang)
    if len(k1) < 2 or len(k2) < 2:
        return None

    has_spaces = " " in text
    candidate_indices: list[int] = []
    for idx in range(2, len(text) - 1):
        ch_prev = text[idx - 1]
        ch_cur = text[idx]
        if ch_prev in " ,，、;；:：/／—-!！?？":
            candidate_indices.append(idx)
        elif not has_spaces and not (ch_prev.isascii() and ch_prev.isalnum() and ch_cur.isascii() and ch_cur.isalnum()):
            candidate_indices.append(idx)
    if not candidate_indices:
        return None

    best_pair: Optional[tuple[float, str, str]] = None
    target_frac = len(k1) / float(max(1, len(k1) + len(k2)))
    for idx in candidate_indices:
        left = text[:idx].strip(" ,，、")
        right = text[idx:].strip(" ,，、")
        kl = normalize_lyric_key(left, lang)
        kr = normalize_lyric_key(right, lang)
        if len(kl) < 2 or len(kr) < 2:
            continue
        s1 = _key_similarity(k1, kl)
        s2 = _key_similarity(k2, kr)
        if s1 < 0.48 or s2 < 0.48:
            continue
        frac = len(kl) / float(max(1, len(kl) + len(kr)))
        score = 0.5 * (s1 + s2) - 0.12 * abs(frac - target_frac)
        if best_pair is None or score > best_pair[0]:
            best_pair = (score, left, right)

    if best_pair is None or best_pair[0] < 0.54:
        return None
    return best_pair[1], best_pair[2]


def _whole_song_similarity(asr_keys: list[str], ref_keys: list[str]) -> float:
    joined_asr = "".join(asr_keys)
    joined_ref = "".join(ref_keys)
    if len(joined_asr) < 10 or len(joined_ref) < 10:
        return 0.0
    ga = _char_ngrams(joined_asr, 2)
    gb = _char_ngrams(joined_ref, 2)
    tot = sum(ga.values())
    ngram_cov = (sum((ga & gb).values()) / float(tot)) if tot else 0.0
    if _has_cjk_ideographs(joined_asr) or _has_cjk_ideographs(joined_ref):
        ga1 = _char_ngrams(joined_asr, 1)
        gb1 = _char_ngrams(joined_ref, 1)
        tot1 = sum(ga1.values())
        uni_cov = (sum((ga1 & gb1).values()) / float(tot1)) if tot1 else 0.0
        ngram_cov = 0.60 * ngram_cov + 0.40 * uni_cov
    matcher = SequenceMatcher(None, joined_asr, joined_ref, autojunk=False)
    sig = sum(b.size for b in matcher.get_matching_blocks() if b.size >= 3)
    seq_cov = sig / float(max(1, len(joined_asr)))
    return 0.65 * ngram_cov + 0.35 * seq_cov


def _align_single_reference(
    cues: list[dict],
    ref_lines: list[str],
    *,
    lang: str = "",
) -> tuple[list[dict], dict[str, Any]]:
    n = len(cues)
    m = len(ref_lines)
    report: dict[str, Any] = {
        "snapped_cues": 0,
        "total_cues": n,
        "whole_song_score": 0.0,
        "mode": "none",
        "weighted_score": 0.0,
    }
    if n == 0 or m == 0:
        return [dict(c) for c in cues], report

    asr_texts = [str(c.get("text") or "").strip() for c in cues]
    asr_keys = [normalize_lyric_key(t, lang) for t in asr_texts]
    ref_keys = [normalize_lyric_key(r, lang) for r in ref_lines]

    whole_score = _whole_song_similarity(asr_keys, ref_keys)
    report["whole_song_score"] = round(whole_score, 3)

    # Precompute merged reference keys for 1:2 and 1:3 spans
    ref_join_2 = [f"{ref_lines[j]} {ref_lines[j + 1]}" for j in range(max(0, m - 1))]
    ref_key_2 = [ref_keys[j] + ref_keys[j + 1] for j in range(max(0, m - 1))]
    ref_join_3 = [f"{ref_lines[j]} {ref_lines[j + 1]} {ref_lines[j + 2]}" for j in range(max(0, m - 2))]
    ref_key_3 = [ref_keys[j] + ref_keys[j + 1] + ref_keys[j + 2] for j in range(max(0, m - 2))]

    # Check if there are strong local anchors (for covers or medleys)
    strong_anchor_hits = 0
    for ak in asr_keys:
        if len(ak) < 3:
            continue
        best_hit = 0.0
        for rk in ref_keys:
            s = _key_similarity(ak, rk)
            if s > best_hit:
                best_hit = s
                if best_hit >= 0.80:
                    break
        if best_hit < 0.78:
            for rk2 in ref_key_2:
                s = _key_similarity(ak, rk2)
                if s > best_hit:
                    best_hit = s
                    if best_hit >= 0.80:
                        break
        if best_hit >= 0.76:
            strong_anchor_hits += 1

    is_full_match = (
        whole_score >= 0.36
        or (n >= 8 and whole_score >= 0.28)
        or (whole_score >= 0.22 and n > 0 and strong_anchor_hits >= max(3, int(n * 0.40)))
    )
    is_medley_partial = (not is_full_match) and strong_anchor_hits >= 2
    if not is_full_match and not is_medley_partial:
        return [dict(c) for c in cues], report

    min_sim = 0.55 if is_full_match else 0.76
    report["mode"] = "full" if is_full_match else "partial_medley"

    # Global monotonic DP over (0..n, 0..m)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    back: list[list[Optional[tuple[int, int, float, Any]]]] = [[None] * (m + 1) for _ in range(n + 1)]

    for i in range(n + 1):
        for j in range(m + 1):
            cur = dp[i][j]
            # Skip ASR cue i -> keep Whisper text untouched
            if i < n and cur >= dp[i + 1][j]:
                if cur > dp[i + 1][j] or back[i + 1][j] is None:
                    dp[i + 1][j] = cur
                    back[i + 1][j] = (i, j, 0.0, None)
            # Skip Ref line j -> unsung line (short/TV-size/medley)
            if j < m and cur >= dp[i][j + 1]:
                if cur > dp[i][j + 1] or back[i][j + 1] is None:
                    dp[i][j + 1] = cur
                    back[i][j + 1] = (i, j, 0.0, None)

            if i >= n or j >= m:
                continue
            ak = asr_keys[i]
            if len(ak) < 2:
                continue

            # Transition (1, 1): 1 ASR cue <-> 1 Ref line (strict length bounds prevent dropping/adding clauses!)
            rk1 = ref_keys[j]
            if rk1 and 0.74 <= (len(ak) / float(len(rk1))) <= 1.32:
                sim1 = _key_similarity(ak, rk1)
                eff_min = min_sim if len(ak) >= 4 else max(min_sim, 0.74)
                if sim1 >= eff_min:
                    gain = (sim1 - eff_min + 0.12) * max(3, min(len(ak), 24))
                    cand = cur + gain
                    if cand > dp[i + 1][j + 1]:
                        dp[i + 1][j + 1] = cand
                        back[i + 1][j + 1] = (i, j, sim1, ("1:1", ref_lines[j]))

            # Transition (1, 2): 1 merged ASR cue <-> 2 consecutive Ref lines
            if j + 1 < m:
                rk2 = ref_key_2[j]
                tail2 = ref_keys[j + 1][-4:] if len(ref_keys[j + 1]) >= 4 else ref_keys[j + 1]
                tail2_ok = (not tail2) or (_key_similarity(ak[-max(len(tail2) + 2, 4):], tail2) >= 0.45)
                if tail2_ok and rk2 and 0.76 <= (len(ak) / float(len(rk2))) <= 1.30 and len(ref_join_2[j]) <= 120:
                    sim2 = _key_similarity(ak, rk2)
                    if sim2 >= max(min_sim, 0.60):
                        gain = (sim2 - min_sim + 0.14) * max(4, min(len(ak), 28))
                        cand = cur + gain
                        if cand > dp[i + 1][j + 2]:
                            dp[i + 1][j + 2] = cand
                            back[i + 1][j + 2] = (i, j, sim2, ("1:2", ref_join_2[j]))

            # Transition (1, 3): 1 long ASR cue <-> 3 short consecutive Ref lines
            if j + 2 < m:
                rk3 = ref_key_3[j]
                tail3 = ref_keys[j + 2][-4:] if len(ref_keys[j + 2]) >= 4 else ref_keys[j + 2]
                tail3_ok = (not tail3) or (_key_similarity(ak[-max(len(tail3) + 2, 4):], tail3) >= 0.45)
                if tail3_ok and rk3 and 0.78 <= (len(ak) / float(len(rk3))) <= 1.28 and len(ref_join_3[j]) <= 140:
                    sim3 = _key_similarity(ak, rk3)
                    if sim3 >= max(min_sim, 0.64):
                        gain = (sim3 - min_sim + 0.15) * max(5, min(len(ak), 32))
                        cand = cur + gain
                        if cand > dp[i + 1][j + 3]:
                            dp[i + 1][j + 3] = cand
                            back[i + 1][j + 3] = (i, j, sim3, ("1:3", ref_join_3[j]))

            # Transition (2, 1): 2 split ASR cues <-> 1 Ref line
            if i + 1 < n and len(asr_keys[i + 1]) >= 2 and rk1:
                comb_k = ak + asr_keys[i + 1]
                if 0.58 <= (len(comb_k) / float(len(rk1))) <= 1.65:
                    sim_21 = _key_similarity(comb_k, rk1)
                    if sim_21 >= max(min_sim, 0.62):
                        split_pair = _split_reference_for_two_cues(
                            ref_lines[j], asr_texts[i], asr_texts[i + 1], lang
                        )
                        if split_pair is not None:
                            gain = (sim_21 - min_sim + 0.14) * max(4, min(len(comb_k), 28))
                            cand = cur + gain
                            if cand > dp[i + 2][j + 1]:
                                dp[i + 2][j + 1] = cand
                                back[i + 2][j + 1] = (i, j, sim_21, ("2:1", split_pair))

    # Backtrack optimal alignment
    out = [dict(c) for c in cues]
    matched_map: dict[int, tuple[int, int, float]] = {}
    ci, cj = n, m
    snapped = 0
    while ci > 0 or cj > 0:
        step = back[ci][cj]
        if step is None:
            if ci > 0:
                ci -= 1
            else:
                cj -= 1
            continue
        pi, pj, sim, payload = step
        if payload is not None:
            kind, val = payload
            if kind in ("1:1", "1:2", "1:3"):
                out[pi]["text"] = _harmonize_adlib_tail(asr_texts[pi], val, lang)
                matched_map[pi] = (pj, cj, sim)
                snapped += 1
            elif kind == "2:1":
                part_a, part_b = val
                out[pi]["text"] = part_a
                out[pi + 1]["text"] = _harmonize_adlib_tail(asr_texts[pi + 1], part_b, lang)
                matched_map[pi] = (pj, cj, sim)
                matched_map[pi + 1] = (pj, cj, sim)
                snapped += 2
        ci, cj = pi, pj

    # Sandwich-Anchor Homophone Rescue (full-match mode only):
    # If ASR cue `i` sits strictly between two confident adjacent anchors (i-1 -> ..j) and (i+1 -> j+1..),
    # rescue tough homophones when length and script agree and similarity >= 0.32.
    if is_full_match and n >= 3:
        for i in range(1, n - 1):
            if i in matched_map:
                continue
            prev_m = matched_map.get(i - 1)
            next_m = matched_map.get(i + 1)
            if not prev_m or not next_m:
                continue
            if prev_m[1] + 1 != next_m[0]:
                continue
            ref_idx = prev_m[1]
            if prev_m[2] < 0.65 or next_m[2] < 0.65 or not (0 <= ref_idx < m):
                continue
            ak = asr_keys[i]
            rk = ref_keys[ref_idx]
            if len(ak) < 3 or len(rk) < 3:
                continue
            ratio_len = len(ak) / float(len(rk))
            sim_mid = _key_similarity(ak, rk)
            if 0.60 <= ratio_len <= 1.55 and sim_mid >= 0.30:
                out[i]["text"] = _harmonize_adlib_tail(asr_texts[i], ref_lines[ref_idx], lang)
                matched_map[i] = (ref_idx, ref_idx + 1, sim_mid)
                snapped += 1

    report["snapped_cues"] = snapped
    report["weighted_score"] = round(dp[n][m], 3)
    return out, report


def snap_asr_cues_to_reference(
    cues: list[dict],
    reference_candidates: str | Iterable[str | dict],
    *,
    lang: str = "",
) -> tuple[list[dict], dict[str, Any]]:
    """Upgrade Whisper ASR cues' wording using the best-matching reference lyric while preserving exact timestamps."""
    if not cues:
        return [], {"snapped_cues": 0, "total_cues": 0, "whole_song_score": 0.0, "mode": "none"}

    raw_list: list[tuple[str, str]] = []
    if isinstance(reference_candidates, str):
        if reference_candidates.strip():
            raw_list.append(("", reference_candidates))
    elif reference_candidates is not None:
        for item in reference_candidates:
            if isinstance(item, str) and item.strip():
                raw_list.append(("", item))
            elif isinstance(item, dict):
                txt = str(item.get("plain_lyrics") or item.get("lyrics") or "").strip()
                label = f"{item.get('track_name', '')} - {item.get('artist_name', '')}".strip(" -")
                if txt:
                    raw_list.append((label, txt))

    seen_keys: set[str] = set()
    best_out = [dict(c) for c in cues]
    best_rep: dict[str, Any] = {
        "snapped_cues": 0,
        "total_cues": len(cues),
        "whole_song_score": 0.0,
        "mode": "none",
        "selected_track": "",
        "selected_lyrics": "",
    }
    best_rank = (0, 0.0, 0.0)

    for label, raw_txt in raw_list[:5]:
        lines = extract_reference_lines(raw_txt)
        if not lines:
            continue
        dedup_sig = normalize_lyric_key("".join(lines[:6]), lang)[:120]
        if dedup_sig in seen_keys:
            continue
        seen_keys.add(dedup_sig)

        cand_out, cand_rep = _align_single_reference(cues, lines, lang=lang)
        rank = (
            1 if cand_rep["snapped_cues"] > 0 else 0,
            float(cand_rep.get("weighted_score", 0.0)),
            float(cand_rep.get("whole_song_score", 0.0)),
        )
        if rank > best_rank:
            best_rank = rank
            best_out = cand_out
            best_rep = dict(cand_rep, selected_track=label, selected_lyrics=raw_txt)

    return best_out, best_rep
