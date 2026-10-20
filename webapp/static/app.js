"use strict";

/* ════════════════════════════════════════════
   Helpers
   ════════════════════════════════════════════ */
const $ = (id) => document.getElementById(id);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem("ytarabic." + key);
    localStorage.setItem("ytarabic." + key, value);
  } catch { /* private mode — preferences just won't persist */ }
  return null;
}

const ICONS = {
  download: '<path d="M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5M5 20h14"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M10 9.2v5.6l4.6-2.8z"/>',
  text: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  resume: '<path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.7"/><path d="M4 4v4.7h4.7"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.6 3.5 5.4 3.5 8.5s-1.1 5.9-3.5 8.5c-2.4-2.6-3.5-5.4-3.5-8.5s1.1-5.9 3.5-8.5z"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/>',
  clipboard: '<rect x="6" y="4.5" width="12" height="16" rx="2"/><path d="M9.5 4.5V3.8c0-.7.5-1.3 1.2-1.3h2.6c.7 0 1.2.6 1.2 1.3v.7"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
  refresh: '<path d="M20 12a8 8 0 1 1-2.35-5.65L20 8.7"/><path d="M20 4v4.7h-4.7"/>',
  folder: '<path d="M3.5 7.5a2 2 0 0 1 2-2h3.8l2 2h7.2a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z"/>',
  hash: '<path d="M5 9h15M4 15h15M10 4L8 20M16 4l-2 16"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v5M14 11v5"/>',
  eraser: '<path d="M8.5 19.5h11M4.6 14.6l8.9-8.9a2 2 0 0 1 2.8 0l2.5 2.5a2 2 0 0 1 0 2.8l-7.4 7.4a3.6 3.6 0 0 1-5.1 0l-1.7-1.7a1.5 1.5 0 0 1 0-2.1zM9 10.2l5.3 5.3"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"/>',
  sparkle: '<path d="M12 3.5l1.7 5 5 1.7-5 1.7-1.7 5-1.7-5-5-1.7 5-1.7zM18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/>',
  more: '<circle cx="5.5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18.5" cy="12" r="1.3"/>',
  cc: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M10.5 10.2a2.2 2.2 0 1 0 0 3.6M17 10.2a2.2 2.2 0 1 0 0 3.6"/>',
  layers: '<path d="M12 4l8.5 4.5L12 13 3.5 8.5z"/><path d="M3.5 12.5L12 17l8.5-4.5M3.5 16.5L12 21l8.5-4.5"/>',
  music: '<path d="M9 18V5.5l10-2V16"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
  alert: '<path d="M12 4l9 15.5H3z"/><path d="M12 10v4.2M12 17h.01"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8h.01"/>',
  list: '<path d="M9 6.5h11M9 12h11M9 17.5h11M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01"/>',
  youtube: '<rect x="2.8" y="5.5" width="18.4" height="13" rx="3.5"/><path d="M10.2 9.4v5.2l4.4-2.6z"/>',
  instagram: '<rect x="4" y="4" width="16" height="16" rx="4.5"/><circle cx="12" cy="12" r="3.6"/><path d="M16.8 7.2h.01"/>',
  external: '<path d="M14 4h6v6M20 4l-8.5 8.5M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
  bell: '<path d="M6.5 16.5V11a5.5 5.5 0 1 1 11 0v5.5l1.5 1.5H5z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
};
const FILLED = new Set(["play"]);

function icon(name, cls = "") {
  return `<svg class="ic ${FILLED.has(name) ? "fill " : ""}${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}
function hydrateIcons(root = document) {
  $$("i[data-icon]", root).forEach((el) => {
    const tmp = document.createElement("span");
    tmp.innerHTML = icon(el.dataset.icon, el.className);
    el.replaceWith(tmp.firstChild);
  });
}

/* ════════════════════════════════════════════
   i18n — English / Arabic (RTL)
   ════════════════════════════════════════════ */
const I18N = {
  en: {
    tagline: "YouTube · Instagram · X — with automatic Arabic subtitles",
    tab_download: "Download", tab_library: "Library", tab_transcripts: "Transcripts",
    tab_resume: "Resume", tab_history: "History", tab_settings: "Settings",
    url_placeholder: "Paste a YouTube, Instagram or X link…",
    url_hint: "One link, or several (one per line) to queue them all. Press Enter to start.",
    paste: "Paste", clear: "Clear", refresh: "Refresh", close: "Close", cancel: "Cancel", delete: "Delete",
    quality: "Quality", subtitles: "Subtitles",
    sub_ar: "Arabic", sub_ar_en: "Arabic + English", sub_en: "English only", sub_none: "No subtitles",
    embed_subs: "Embed subtitles into the video file", also_transcript: "Also save a transcript",
    start_download: "Download", add_to_queue: "Add to queue", download_playlist_n: "Download {n} videos",
    queue_n_links: "Queue {n} links",
    recent_activity: "Recent activity", see_all: "See all",
    q_audio: "MP3", q_audio_sub: "Audio only",
    q_sub_1: "2160p", q_sub_2: "Full HD", q_sub_3: "HD", q_sub_4: "SD", q_sub_5: "Low",
    supported: "Works with:", any_site: "+ most video sites",
    probing: "Reading the link…",
    views: "{n} views", n_videos: "{n} videos", chapters_n: "{n} chapters",
    ar_manual: "Human-made Arabic subtitle", ar_youtube: "Arabic: YouTube's translation",
    ar_gemini: "Arabic: Gemini translation", ar_google: "Arabic: Google Translate",
    no_subs_site: "Subtitles: YouTube only",
    in_playlist: "This video is part of a playlist.",
    this_video: "This video", whole_playlist: "Whole playlist",
    select_all: "All", select_none: "None", selected_n: "{n} of {total} selected",
    select_range: "Pick e.g. 1-10, 15", apply: "Apply",
    batch_title: "{n} links — each one is queued and downloaded in turn",
    instagram_title: "Instagram reel", instagram_hint: "Private accounts need INSTAGRAM_COOKIES_FILE in .env.",
    x_title: "X / Twitter post",
    x_hint: "Download the video below, or save the post's text and images:",
    extract_thread: "Extract X thread",
    probe_failed: "Couldn't read this link",
    enter_url: "Paste a link first.", select_one: "Select at least one video.",
    download_started: "Download started.", added_to_queue: "Added to the queue.",
    queued_n: "{n} downloads queued.",
    // library
    search_library: "Search downloaded videos…",
    filter_all: "All", filter_missing_ar: "Missing Arabic", filter_video: "Videos", filter_audio: "Audio",
    open_folder: "Open folder", show_in_folder: "Show in folder",
    lib_stats: "{n} files · {size}", lib_empty: "Nothing downloaded yet.", lib_no_match: "No downloads match.",
    leftovers: "{size} of leftover partial files from interrupted downloads can be freed.",
    leftovers_unfinished: "{n} unfinished download(s) ({size}) can still be resumed.",
    review_cleanup: "Review & clean up",
    play: "Play", root_folder: "downloads",
    no_subtitle: "No subtitle", human: "Human",
    m_subtitles: "Subtitles", m_get_ar: "Get Arabic subtitle (best available)", m_refetch_ar: "Re-fetch Arabic subtitle (best available)",
    m_gemini: "Translate with Gemini", m_youtube: "Use YouTube's Arabic translation",
    m_google: "Translate with Google", m_english: "Get English subtitle",
    m_more: "More", m_embed: "Embed subtitles into the file", m_transcript: "Extract transcript",
    m_open_yt: "Open on YouTube",
    no_id: "No YouTube id in the file name — subtitles can't be looked up for this one.",
    // player
    subs_off: "Off", cant_play: "Your browser can't play this file's format. Open it in your usual video player instead.",
    // transcripts
    transcript_placeholder: "YouTube video, or X / Twitter post link",
    transcript_lang: "Language", lang_auto: "Video's own language",
    with_timestamps: "Timestamps on every line",
    extract_transcript: "Extract transcript",
    transcript_hint: "A YouTube transcript is saved as plain text, split by chapters — ready to read, copy into an AI chat, or summarize here with Gemini.",
    saved_transcripts: "Saved transcripts", tr_empty: "No transcripts yet.",
    words_n: "{n} words", view: "View", copy: "Copy", copied: "Copied to clipboard.",
    summarize: "Summarize", summary_ar: "Summary (Arabic)", summary_en: "Summary (English)",
    transcript: "Transcript", summarize_in: "Summarize in {lang}",
    summary_started: "Summarizing with Gemini — it'll open here when ready.",
    needs_gemini: "Summaries need a Gemini API key (GEMINI_API_KEY in .env).",
    kind_tweet_short: "X",
    // resume
    resume_hint: "Playlists and videos that didn't finish — pick up exactly where they stopped.",
    resume_empty: "Nothing to resume — every download finished.",
    resume: "Resume", videos: "Videos", forget: "Remove from list",
    stopped_mid: "stopped mid-download", done_of: "{done} of {total} done", done_n: "{n} done",
    selected_only: "{n} selected", downloaded: "downloaded", not_yet: "not yet", skipped: "not selected",
    forget_confirm: "Remove this from the Resume list? (Downloaded files are kept.)",
    // history
    search_history: "Search history…",
    kind_video: "Video", kind_playlist: "Playlist", kind_transcript: "Transcript", kind_summary: "Summary",
    kind_subtitle: "Subtitle", kind_tweet: "X thread", kind_instagram: "Instagram",
    status_all: "Any status", status_success: "Succeeded", status_failed: "Failed", status_cancelled: "Stopped",
    clear_history: "Clear", clear_history_confirm: "Clear the whole download history? (Files are kept.)",
    hist_empty: "Nothing here yet.", retry: "Retry", again: "Run again", open_link: "Open link",
    // settings
    set_downloads: "Downloads", set_default_quality: "Default quality",
    set_rate_limit: "Speed limit", set_rate_limit_hint: "0 = unlimited. Handy so a big download doesn't eat the whole connection.",
    set_sub_mode: "Subtitles by default",
    set_embed: "Embed subtitles into the video file by default (soft track — can be switched off in the player)",
    set_translation: "Arabic translation",
    set_translation_hint: "A real (human-made) Arabic subtitle is always used first when YouTube has one. Otherwise:",
    order_youtube: "YouTube's translation first",
    order_youtube_hint: "Instant and free. Gemini is only used when YouTube has no Arabic translation.",
    order_gemini: "Gemini first",
    order_gemini_hint: "Usually more natural — reads the whole video for context. Uses your free Gemini quota.",
    set_gemini_model: "Gemini model",
    set_gemini_model_hint: "Used for translation and summaries. Change it here instead of in the code when Google releases a new model.",
    set_transcripts: "Transcripts & summaries", set_summary_lang: "Summary language",
    set_interface: "Interface", set_ui_lang: "Interface language",
    set_notify: "Desktop notification when a download finishes (while this tab is in the background)",
    set_environment: "Setup", reset_defaults: "Reset to defaults", autosave_hint: "Changes are saved automatically.",
    saved: "Saved.", reset_confirm: "Reset every setting to its default?",
    env_ffmpeg: "FFmpeg", env_ffmpeg_missing: "Not found — needed above 360p and for MP3. Install: winget install Gyan.FFmpeg, then restart.",
    env_cookies: "YouTube cookies", env_cookies_missing: "Not set — only needed if YouTube asks you to sign in. Set YT_COOKIES_FILE in .env.",
    env_ig: "Instagram cookies", env_ig_missing: "Not set — only needed for private accounts (INSTAGRAM_COOKIES_FILE).",
    env_gemini: "Gemini API key", env_gemini_missing: "Not set — free key at aistudio.google.com/apikey, then GEMINI_API_KEY in .env.",
    env_folder: "Downloads folder", env_version: "Version", env_set: "Set", env_found: "Found",
    notify_denied: "Notifications are blocked for this page in the browser settings.",
    // console
    activity: "Activity", stop: "Stop", clear_log: "Clear log", log_empty: "Waiting for a job…",
    idle: "Idle", working: "Working…", processing: "Processing…", eta: "{t} left",
    up_next: "Up next ({n})", clear_queue: "Clear", remove: "Remove",
    item_of: "Video {i} of {n}",
    // events
    saved_toast: "Saved: {title}", transcript_ready: "Transcript ready.", summary_ready: "Summary ready.",
    notif_done: "Download finished", notif_failed: "Download failed", notif_cancelled: "Download stopped",
    cleanup_title: "Clean up leftover files",
    cleanup_intro: "These are partial files left behind by interrupted downloads whose finished video is already there — safe to delete.",
    cleanup_none: "No leftover files to clean up.",
    cleanup_unfinished: "Also delete {n} unfinished download(s) ({size}) — they can't be resumed afterwards",
    cleanup_delete_n: "Delete {n} files ({size})", cleaned: "Freed {size}.",
    request_failed: "Request failed.", server_unreachable: "Can't reach the ytarabic server — is it still running?",
    confirm_stop: "Stop the current job?",
  },
  ar: {
    tagline: "يوتيوب · إنستغرام · إكس — مع ترجمة عربية تلقائية",
    tab_download: "تحميل", tab_library: "المكتبة", tab_transcripts: "النصوص",
    tab_resume: "استكمال", tab_history: "السجل", tab_settings: "الإعدادات",
    url_placeholder: "الصق رابط يوتيوب أو إنستغرام أو إكس…",
    url_hint: "رابط واحد، أو عدة روابط (كل رابط بسطر) لإضافتها كلها إلى قائمة الانتظار. اضغط Enter للبدء.",
    paste: "لصق", clear: "مسح", refresh: "تحديث", close: "إغلاق", cancel: "إلغاء", delete: "حذف",
    quality: "الجودة", subtitles: "الترجمة",
    sub_ar: "عربي", sub_ar_en: "عربي + إنكليزي", sub_en: "إنكليزي فقط", sub_none: "بدون ترجمة",
    embed_subs: "دمج الترجمة داخل ملف الفيديو", also_transcript: "حفظ نص الفيديو أيضاً",
    start_download: "تحميل", add_to_queue: "إضافة لقائمة الانتظار", download_playlist_n: "تحميل {n} فيديو",
    queue_n_links: "إضافة {n} روابط للانتظار",
    recent_activity: "آخر النشاطات", see_all: "عرض الكل",
    q_audio: "MP3", q_audio_sub: "صوت فقط",
    q_sub_1: "2160p", q_sub_2: "Full HD", q_sub_3: "HD", q_sub_4: "SD", q_sub_5: "منخفضة",
    supported: "يعمل مع:", any_site: "+ معظم مواقع الفيديو",
    probing: "جارٍ قراءة الرابط…",
    views: "{n} مشاهدة", n_videos: "{n} فيديو", chapters_n: "{n} فصول",
    ar_manual: "ترجمة عربية بشرية", ar_youtube: "العربية: ترجمة يوتيوب",
    ar_gemini: "العربية: ترجمة Gemini", ar_google: "العربية: ترجمة Google",
    no_subs_site: "الترجمة: ليوتيوب فقط",
    in_playlist: "هذا الفيديو جزء من قائمة تشغيل.",
    this_video: "هذا الفيديو", whole_playlist: "القائمة كاملة",
    select_all: "الكل", select_none: "لا شيء", selected_n: "محدد {n} من {total}",
    select_range: "مثلاً 1-10, 15", apply: "تطبيق",
    batch_title: "{n} روابط — يُضاف كل رابط لقائمة الانتظار ويُحمّل بالترتيب",
    instagram_title: "مقطع إنستغرام", instagram_hint: "الحسابات الخاصة تحتاج INSTAGRAM_COOKIES_FILE في ملف .env",
    x_title: "منشور إكس / تويتر",
    x_hint: "حمّل الفيديو من الأسفل، أو احفظ نص المنشور وصوره:",
    extract_thread: "استخراج سلسلة إكس",
    probe_failed: "تعذّرت قراءة الرابط",
    enter_url: "الصق رابطاً أولاً.", select_one: "اختر فيديو واحداً على الأقل.",
    download_started: "بدأ التحميل.", added_to_queue: "أُضيف إلى قائمة الانتظار.",
    queued_n: "أُضيفت {n} تحميلات للانتظار.",
    search_library: "ابحث في الفيديوهات المحمّلة…",
    filter_all: "الكل", filter_missing_ar: "بدون ترجمة عربية", filter_video: "فيديو", filter_audio: "صوت",
    open_folder: "فتح المجلد", show_in_folder: "إظهار في المجلد",
    lib_stats: "{n} ملف · {size}", lib_empty: "لا يوجد شيء محمّل بعد.", lib_no_match: "لا توجد نتائج مطابقة.",
    leftovers: "يمكن تحرير {size} من ملفات جزئية تركتها تحميلات انقطعت.",
    leftovers_unfinished: "{n} تحميل غير مكتمل ({size}) ما زال قابلاً للاستكمال.",
    review_cleanup: "مراجعة وتنظيف",
    play: "تشغيل", root_folder: "downloads",
    no_subtitle: "بدون ترجمة", human: "بشرية",
    m_subtitles: "الترجمة", m_get_ar: "جلب ترجمة عربية (أفضل المتاح)", m_refetch_ar: "إعادة جلب الترجمة العربية (أفضل المتاح)",
    m_gemini: "ترجمة باستخدام Gemini", m_youtube: "استخدام ترجمة يوتيوب العربية",
    m_google: "ترجمة باستخدام Google", m_english: "جلب الترجمة الإنكليزية",
    m_more: "المزيد", m_embed: "دمج الترجمة داخل الملف", m_transcript: "استخراج النص",
    m_open_yt: "فتح على يوتيوب",
    no_id: "اسم الملف لا يحتوي معرّف يوتيوب — لا يمكن البحث عن ترجمته.",
    subs_off: "إيقاف", cant_play: "المتصفح لا يستطيع تشغيل صيغة هذا الملف. افتحه بمشغل الفيديو المعتاد.",
    transcript_placeholder: "رابط فيديو يوتيوب، أو منشور إكس / تويتر",
    transcript_lang: "اللغة", lang_auto: "لغة الفيديو الأصلية",
    with_timestamps: "توقيت بجانب كل سطر",
    extract_transcript: "استخراج النص",
    transcript_hint: "يُحفظ نص فيديو يوتيوب كنص عادي مقسّم حسب الفصول — جاهز للقراءة أو النسخ إلى محادثة ذكاء اصطناعي أو التلخيص هنا عبر Gemini.",
    saved_transcripts: "النصوص المحفوظة", tr_empty: "لا توجد نصوص بعد.",
    words_n: "{n} كلمة", view: "عرض", copy: "نسخ", copied: "تم النسخ.",
    summarize: "تلخيص", summary_ar: "الملخص (عربي)", summary_en: "الملخص (إنكليزي)",
    transcript: "النص", summarize_in: "تلخيص بال{lang}",
    summary_started: "جارٍ التلخيص عبر Gemini — سيظهر هنا عند الانتهاء.",
    needs_gemini: "التلخيص يحتاج مفتاح Gemini ‏(GEMINI_API_KEY في ملف .env).",
    kind_tweet_short: "إكس",
    resume_hint: "قوائم تشغيل وفيديوهات لم يكتمل تحميلها — أكمل من حيث توقفت تماماً.",
    resume_empty: "لا شيء للاستكمال — كل التحميلات اكتملت.",
    resume: "استكمال", videos: "الفيديوهات", forget: "إزالة من القائمة",
    stopped_mid: "توقف أثناء التحميل", done_of: "اكتمل {done} من {total}", done_n: "اكتمل {n}",
    selected_only: "{n} محدد", downloaded: "تم", not_yet: "ليس بعد", skipped: "غير محدد",
    forget_confirm: "إزالة هذا من قائمة الاستكمال؟ (الملفات المحمّلة تبقى كما هي.)",
    search_history: "ابحث في السجل…",
    kind_video: "فيديو", kind_playlist: "قائمة", kind_transcript: "نص", kind_summary: "ملخص",
    kind_subtitle: "ترجمة", kind_tweet: "سلسلة إكس", kind_instagram: "إنستغرام",
    status_all: "أي حالة", status_success: "نجح", status_failed: "فشل", status_cancelled: "أُوقف",
    clear_history: "مسح", clear_history_confirm: "مسح سجل التحميلات بالكامل؟ (الملفات تبقى.)",
    hist_empty: "لا شيء هنا بعد.", retry: "إعادة المحاولة", again: "تشغيل مجدداً", open_link: "فتح الرابط",
    set_downloads: "التحميل", set_default_quality: "الجودة الافتراضية",
    set_rate_limit: "حد السرعة", set_rate_limit_hint: "0 = بلا حد. مفيد حتى لا يستهلك تحميل كبير الإنترنت كله.",
    set_sub_mode: "الترجمة الافتراضية",
    set_embed: "دمج الترجمة داخل ملف الفيديو افتراضياً (مسار ترجمة يمكن إخفاؤه من المشغل)",
    set_translation: "الترجمة العربية",
    set_translation_hint: "تُستخدم الترجمة العربية البشرية أولاً دائماً إن وُجدت على يوتيوب. وإلا:",
    order_youtube: "ترجمة يوتيوب أولاً",
    order_youtube_hint: "فورية ومجانية. يُستخدم Gemini فقط إن لم تتوفر ترجمة يوتيوب العربية.",
    order_gemini: "Gemini أولاً",
    order_gemini_hint: "أكثر طبيعية غالباً — يقرأ الفيديو كاملاً لفهم السياق. يستهلك من حصة Gemini المجانية.",
    set_gemini_model: "نموذج Gemini",
    set_gemini_model_hint: "يُستخدم للترجمة والتلخيص. غيّره من هنا بدل تعديل الكود عند صدور نموذج جديد.",
    set_transcripts: "النصوص والملخصات", set_summary_lang: "لغة الملخص",
    set_interface: "الواجهة", set_ui_lang: "لغة الواجهة",
    set_notify: "إشعار على سطح المكتب عند انتهاء التحميل (عندما تكون الصفحة في الخلفية)",
    set_environment: "التجهيزات", reset_defaults: "استعادة الافتراضي", autosave_hint: "تُحفظ التغييرات تلقائياً.",
    saved: "تم الحفظ.", reset_confirm: "إعادة كل الإعدادات إلى قيمها الافتراضية؟",
    env_ffmpeg: "FFmpeg", env_ffmpeg_missing: "غير موجود — ضروري للجودة فوق 360p ولملفات MP3. للتثبيت: winget install Gyan.FFmpeg ثم أعد التشغيل.",
    env_cookies: "كوكيز يوتيوب", env_cookies_missing: "غير مضبوطة — مطلوبة فقط إن طلب يوتيوب تسجيل الدخول. اضبط YT_COOKIES_FILE في .env",
    env_ig: "كوكيز إنستغرام", env_ig_missing: "غير مضبوطة — مطلوبة فقط للحسابات الخاصة (INSTAGRAM_COOKIES_FILE).",
    env_gemini: "مفتاح Gemini", env_gemini_missing: "غير مضبوط — مفتاح مجاني من aistudio.google.com/apikey ثم GEMINI_API_KEY في .env",
    env_folder: "مجلد التحميل", env_version: "الإصدار", env_set: "مضبوط", env_found: "موجود",
    notify_denied: "الإشعارات محظورة لهذه الصفحة من إعدادات المتصفح.",
    activity: "النشاط", stop: "إيقاف", clear_log: "مسح السجل", log_empty: "بانتظار مهمة…",
    idle: "خامل", working: "جارٍ العمل…", processing: "جارٍ المعالجة…", eta: "متبقٍ {t}",
    up_next: "التالي ({n})", clear_queue: "مسح", remove: "إزالة",
    item_of: "الفيديو {i} من {n}",
    saved_toast: "تم الحفظ: {title}", transcript_ready: "النص جاهز.", summary_ready: "الملخص جاهز.",
    notif_done: "انتهى التحميل", notif_failed: "فشل التحميل", notif_cancelled: "أُوقف التحميل",
    cleanup_title: "تنظيف الملفات المتبقية",
    cleanup_intro: "هذه ملفات جزئية تركتها تحميلات انقطعت ثم اكتملت لاحقاً — الفيديو الكامل موجود، فحذفها آمن.",
    cleanup_none: "لا توجد ملفات متبقية للتنظيف.",
    cleanup_unfinished: "احذف أيضاً {n} تحميل غير مكتمل ({size}) — لن يمكن استكمالها بعد ذلك",
    cleanup_delete_n: "حذف {n} ملف ({size})", cleaned: "تم تحرير {size}.",
    request_failed: "فشل الطلب.", server_unreachable: "لا يمكن الوصول إلى خادم ytarabic — هل ما زال يعمل؟",
    confirm_stop: "إيقاف المهمة الحالية؟",
  },
};

let lang = store("lang") || ((navigator.language || "").startsWith("ar") ? "ar" : "en");
if (!I18N[lang]) lang = "en";

function t(key, vars) {
  let s = I18N[lang][key] ?? I18N.en[key] ?? key;
  if (vars) s = s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ""));
  return s;
}
const locale = () => (lang === "ar" ? "ar-u-nu-latn" : "en");

function applyLang() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  $$("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  $$("[data-i18n-ph]").forEach((el) => (el.placeholder = t(el.dataset.i18nPh)));
  $$("[data-i18n-title]").forEach((el) => (el.title = t(el.dataset.i18nTitle)));
  $("langLabel").textContent = lang === "ar" ? "English" : "عربي";
  $("log").dataset.empty = t("log_empty");
  $("setUiLang").value = lang;
  fixLinkInputDir();
}

// Links are always left-to-right, but an Arabic placeholder isn't
function fixLinkInputDir() {
  for (const el of [$("dlUrl"), $("exUrl")]) el.dir = el.value ? "ltr" : (lang === "ar" ? "rtl" : "ltr");
}

function setLang(next) {
  lang = next;
  store("lang", next);
  applyLang();
  renderAll();
}

/* ════════════════════════════════════════════
   Formatting
   ════════════════════════════════════════════ */
// Numbers with Latin units ("298 KB", "1:05:12") get flipped into "KB 298"
// inside Arabic text — wrap them in a left-to-right isolate.
const ltr = (s) => (lang === "ar" ? `⁦${s}⁩` : s);

function fmtBytes(b) {
  if (!b || b <= 0) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return ltr(`${b.toFixed(i >= 2 ? 1 : 0)} ${u[i]}`);
}
function fmtDuration(s) {
  s = Math.max(0, Math.round(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return ltr(h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`);
}
function fmtNumber(n) {
  try { return new Intl.NumberFormat(locale(), { notation: "compact", maximumFractionDigits: 1 }).format(n); }
  catch { return String(n); }
}
function fmtWhen(value) {
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (isNaN(d)) return "";
  return d.toLocaleString(locale(), { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function fmtUploadDate(yyyymmdd) {
  if (!yyyymmdd || yyyymmdd.length !== 8) return "";
  const d = new Date(+yyyymmdd.slice(0, 4), +yyyymmdd.slice(4, 6) - 1, +yyyymmdd.slice(6));
  return d.toLocaleDateString(locale(), { year: "numeric", month: "short", day: "numeric" });
}
const LANG_NAMES = { ar: "العربية", en: "English", de: "Deutsch", fr: "Français", es: "Español", ja: "日本語", ko: "한국어", zh: "中文", tr: "Türkçe" };
function langName(code) {
  const base = (code || "").split("-")[0];
  const name = LANG_NAMES[base] || code;
  return code && code !== base ? `${name} (${code})` : name;
}
function shortSource(src) {
  if (!src) return "";
  if (src.startsWith("Gemini")) return src.includes("+") ? "Gemini*" : "Gemini";
  if (src.startsWith("YouTube")) return "YouTube";
  if (src.startsWith("Manual")) return t("human");
  if (src.startsWith("Google")) return "Google";
  return src;
}

/* ════════════════════════════════════════════
   API + toasts
   ════════════════════════════════════════════ */
async function request(path, body, { quiet = false } = {}) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  try {
    const res = await fetch(path, opts);
    const data = await res.json();
    if (data && data.ok === false && !quiet) toast(data.error || t("request_failed"), "error");
    return data;
  } catch (e) {
    if (!quiet) toast(t("server_unreachable"), "error");
    return { ok: false, error: String(e) };
  }
}
const get = (path, opts) => request(path, undefined, opts);
const post = (path, body = {}, opts) => request(path, body, opts);

const TOAST_ICON = { success: "check", error: "alert", warn: "alert", info: "info" };
function toast(message, level = "info", actions = []) {
  const box = $("toasts");
  const el = document.createElement("div");
  el.className = `toast ${level}`;
  el.innerHTML =
    `<span class="t-ic ${level}">${icon(TOAST_ICON[level] || "info")}</span><span dir="auto">${esc(message)}</span>` +
    actions.map((a, i) => `<button type="button" data-i="${i}">${esc(a.label)}</button>`).join("");
  const remove = () => { el.classList.add("out"); setTimeout(() => el.remove(), 220); };
  el.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => { actions[+b.dataset.i].run(); remove(); })
  );
  box.appendChild(el);
  while (box.childElementCount > 4) box.firstChild.remove();
  setTimeout(remove, actions.length ? 9000 : 4500);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  toast(t("copied"), "success");
}

const openFolder = (path = "") => post("/api/open", { path });

/* ════════════════════════════════════════════
   State
   ════════════════════════════════════════════ */
const state = {
  status: null,
  settings: {},
  busy: false,
  label: "",
  item: null,
  queue: [],
  progress: { fraction: 0 },
  // download tab
  probe: null,
  probeUrl: "",
  playlistMode: false,
  playlistProbe: null,
  selected: new Set(),
  quality: null,
  // lists
  library: null,
  transcripts: [],
  history: [],
  resume: { playlists: [], singles: [] },
  textView: null,
};

/* ════════════════════════════════════════════
   Tabs
   ════════════════════════════════════════════ */
const LOADERS = {
  download: () => loadRecent(),
  library: () => loadLibrary(),
  transcripts: () => loadTranscripts(),
  resume: () => loadResume(),
  history: () => loadHistory(),
  settings: () => renderSettings(),
};
function activeTab() {
  return document.querySelector(".tab.active")?.dataset.tab || "download";
}
function showTab(name) {
  if (!LOADERS[name]) name = "download";
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  LOADERS[name]();
}
$$(".tab").forEach((btn) => btn.addEventListener("click", () => showTab(btn.dataset.tab)));
window.addEventListener("hashchange", () => {
  const name = location.hash.slice(1);
  if (name && name !== activeTab()) showTab(name);
});
document.addEventListener("click", (e) => {
  const go = e.target.closest("[data-goto]");
  if (go) showTab(go.dataset.goto);
});

/* ════════════════════════════════════════════
   Console: log, progress, queue, live events
   ════════════════════════════════════════════ */
const logEl = $("log");

function addLog(message, level = "info") {
  const atBottom = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 40;
  const line = document.createElement("div");
  line.className = level;
  line.dir = "auto";
  line.textContent = message;
  logEl.appendChild(line);
  while (logEl.childElementCount > 2000) logEl.firstChild.remove();
  if (atBottom) logEl.scrollTop = logEl.scrollHeight;
}

function renderProgress() {
  const e = state.progress || {};
  const f = e.fraction || 0;
  const track = $("progressTrack");
  const working = state.busy && !f;
  track.classList.toggle("indeterminate", working);
  $("progressBar").style.width = `${(f * 100).toFixed(1)}%`;
  $("progressPct").textContent = f && state.busy ? `${Math.floor(f * 100)}%` : "";
  let detail;
  if (!state.busy) detail = t("idle");
  else if (e.phase === "processing") detail = t("processing");
  else if (e.total) {
    detail = [
      ltr(`${fmtBytes(e.done)} / ${fmtBytes(e.total)}`),
      e.speed ? `${fmtBytes(e.speed)}/s` : "",
      e.eta != null && e.eta > 0 ? t("eta", { t: fmtDuration(e.eta) }) : "",
    ].filter(Boolean).join("  ·  ");
  } else detail = e.label || t("working");
  $("progressLabel").textContent = detail;
  document.title = state.busy && f ? `${Math.floor(f * 100)}% · ytarabic` : state.busy ? "… ytarabic" : "ytarabic";
}

function renderNow() {
  $("nowBox").classList.toggle("hidden", !state.busy);
  $("nowLabel").textContent = state.label || "";
  $("nowItem").textContent = state.item ? `${t("item_of", { i: state.item.index, n: state.item.total })} — ${state.item.title}` : "";
  $("btnStop").classList.toggle("hidden", !state.busy);
  $("btnStop").disabled = false;
  renderDownloadButton();
}

function setBusy(busy, label) {
  state.busy = busy;
  state.label = busy ? label || state.label : "";
  if (!busy) { state.item = null; state.progress = { fraction: 0 }; }
  renderNow();
  renderProgress();
}

function renderQueue(items) {
  state.queue = items || [];
  const box = $("queueBox");
  if (!state.queue.length) { box.innerHTML = ""; box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  box.innerHTML =
    `<div class="queue-title"><span>${esc(t("up_next", { n: state.queue.length }))}</span>` +
    `<button class="link-btn" type="button" id="btnClearQueue">${esc(t("clear_queue"))}</button></div>` +
    state.queue.map((it, i) => `
      <div class="queue-row">
        <span dir="auto" title="${esc(it.label || it.name)}">${esc(it.label || it.name)}</span>
        <button class="queue-remove" type="button" data-remove="${i}" title="${esc(t("remove"))}">${icon("x")}</button>
      </div>`).join("");
  box.querySelectorAll("[data-remove]").forEach((btn) =>
    btn.addEventListener("click", () => post(`/api/queue/remove?index=${btn.dataset.remove}`, {}))
  );
  $("btnClearQueue").addEventListener("click", () => post("/api/queue/clear", {}));
}

$("btnStop").addEventListener("click", () => {
  $("btnStop").disabled = true;
  post("/api/stop", {});
});
$("btnClearLog").addEventListener("click", () => { logEl.innerHTML = ""; });
$("btnFootFolder").addEventListener("click", () => openFolder());

function handleEvent(e, replaying) {
  switch (e.kind) {
    case "log":
      addLog(e.message, e.level);
      // Between/after downloads (subtitles, translation, transcript...), the
      // latest step is more useful than a bar frozen at 100%.
      if (state.busy && (state.progress.phase === "processing" || !state.progress.fraction)) {
        state.progress = { fraction: 0, label: e.message };
        renderProgress();
      }
      break;
    case "progress": state.progress = e; renderProgress(); break;
    case "item":
      state.item = e;
      state.progress = { fraction: 0 };
      renderNow(); renderProgress();
      addLog(`[${e.index}/${e.total}] ${e.title}`, "item");
      break;
    case "state": setBusy(e.busy, e.label); break;
    case "queued": renderQueue(e.queue); break;
    case "result": if (!replaying) onResult(e); break;
    case "done": if (!replaying) onDone(e); break;
  }
}

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  let ping, replaying = false;
  ws.onopen = () => {
    ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
    loadStatus();
  };
  ws.onmessage = (ev) => {
    const e = JSON.parse(ev.data);
    if (e.kind === "replay-start") { replaying = true; logEl.innerHTML = ""; return; }
    if (e.kind === "replay-end") { replaying = false; return; }
    handleEvent(e, replaying);
  };
  ws.onclose = () => { clearInterval(ping); setTimeout(connect, 1500); };
}

function onResult(e) {
  if (e.type === "media") {
    toast(t("saved_toast", { title: e.title || "" }), "success", [
      { label: t("play"), run: () => playPath(e.path) },
      { label: t("show_in_folder"), run: () => openFolder(e.path) },
    ]);
  } else if (e.type === "transcript") {
    toast(t("transcript_ready"), "success", [{ label: t("view"), run: () => openText(e.path) }]);
    if (activeTab() === "transcripts") loadTranscripts();
  } else if (e.type === "summary") {
    // Reload first — the viewer builds its tabs from the list's "summaries"
    loadTranscripts().then(() => {
      const viewing = state.textView && state.textView.path === e.source && $("textDlg").open;
      if (viewing) openText(e.source, e.path);
      else toast(t("summary_ready"), "success", [{ label: t("view"), run: () => openText(e.source, e.path) }]);
    });
  }
}

function onDone(e) {
  const tab = activeTab();
  if (tab !== "settings") LOADERS[tab]();
  loadResumeBadge();
  if (store("notify") === "1" && document.hidden && "Notification" in window && Notification.permission === "granted") {
    const key = e.status === "failed" ? "notif_failed" : e.status === "cancelled" ? "notif_cancelled" : "notif_done";
    try { new Notification(t(key), { body: e.label || "", tag: "ytarabic" }); } catch { /* ignore */ }
  }
}

/* ════════════════════════════════════════════
   Status (header pills, defaults)
   ════════════════════════════════════════════ */
async function loadStatus() {
  const s = await get("/api/status", { quiet: true });
  if (!s || s.ok === false) return;
  state.status = s;
  state.settings = s.settings || {};
  if (!state.quality) state.quality = state.settings.default_quality || "2";
  renderPills();
  $("downloadDir").textContent = s.download_dir;
  $("downloadDir").parentElement.title = s.download_dir;
  setBusy(s.busy, s.label);
  renderQueue(s.queue);
  applyDownloadDefaults();
  renderQuality();
  if (activeTab() === "settings") renderSettings();
}

function renderPills() {
  const s = state.status;
  if (!s) return;
  $("statusPills").innerHTML = [
    ["FFmpeg", s.ffmpeg, t("env_ffmpeg_missing")],
    ["Cookies", s.cookies, t("env_cookies_missing")],
    ["Gemini", s.gemini, t("env_gemini_missing")],
  ].map(([label, on, tip]) =>
    `<span class="pill ${on ? "on" : label === "Cookies" ? "" : "off"}" data-goto="settings" title="${esc(on ? label : tip)}">${label}</span>`
  ).join("");
}

/* ════════════════════════════════════════════
   Download tab
   ════════════════════════════════════════════ */
const QUALITY_MAIN = { 1: "4K", 2: "1080p", 3: "720p", 4: "480p", 5: "360p" };
const urlBox = $("dlUrl");
let probeTimer = null;
let probeSeq = 0;
let subModeTouched = false;
let embedTouched = false;

function applyDownloadDefaults() {
  if (!subModeTouched) $("dlSubMode").value = state.settings.subtitle_mode || "ar";
  if (!embedTouched) $("dlEmbed").checked = !!state.settings.embed_subtitles;
}
$("dlSubMode").addEventListener("change", () => { subModeTouched = true; });
$("dlEmbed").addEventListener("change", () => { embedTouched = true; });

function urlsFromBox() {
  return urlBox.value
    .split(/\s+/)
    .map((s) => s.trim())
    .filter((s) => /^(https?:\/\/|www\.|youtu\.be\/|(m\.)?youtube\.com\/|(www\.)?(instagram|x|twitter)\.com\/)/i.test(s));
}

function autoGrow() {
  fixLinkInputDir();
  urlBox.style.height = "auto";
  urlBox.style.height = Math.min(urlBox.scrollHeight, 180) + "px";
  $("btnClearUrl").classList.toggle("hidden", !urlBox.value);
}

urlBox.addEventListener("input", () => {
  autoGrow();
  clearTimeout(probeTimer);
  probeTimer = setTimeout(runProbe, 450);
});
urlBox.addEventListener("paste", () => {
  clearTimeout(probeTimer);
  probeTimer = setTimeout(() => { autoGrow(); runProbe(); }, 30);
});
urlBox.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    startDownload();
  }
});
$("btnPaste").addEventListener("click", async () => {
  try {
    const text = (await navigator.clipboard.readText()).trim();
    if (!text) return;
    urlBox.value = urlBox.value.trim() ? urlBox.value.trim() + "\n" + text : text;
    autoGrow();
    runProbe();
  } catch {
    urlBox.focus();
  }
});
$("btnClearUrl").addEventListener("click", () => {
  urlBox.value = "";
  autoGrow();
  runProbe();
  urlBox.focus();
});

async function runProbe() {
  const urls = urlsFromBox();
  const seq = ++probeSeq;
  if (!urls.length) {
    state.probe = null; state.probeUrl = ""; state.playlistMode = false;
    renderPreview(); renderQuality();
    return;
  }
  if (urls.length > 1) {
    state.probe = { type: "batch", urls }; state.probeUrl = ""; state.playlistMode = false;
    renderPreview(); renderQuality();
    return;
  }
  const url = urls[0];
  if (url === state.probeUrl && state.probe && state.probe.type !== "loading") return;
  state.probeUrl = url;
  state.probe = { type: "loading" };
  state.playlistMode = false;
  state.playlistProbe = null;
  renderPreview();
  const data = await post("/api/probe", { url }, { quiet: true });
  if (seq !== probeSeq) return;
  state.probe = data.ok ? data : { type: "error", error: data.error, kind: data.kind, url };
  if (data.type === "playlist") state.selected = new Set(data.entries.map((e) => e.id));
  renderPreview();
  renderQuality();
}

async function setPlaylistMode(on) {
  state.playlistMode = on;
  const p = state.probe;
  if (on && !state.playlistProbe && p?.playlist_id) {
    state.playlistProbe = { type: "loading" };
    renderPreview();
    const seq = probeSeq;
    const data = await post("/api/probe", { url: `https://www.youtube.com/playlist?list=${p.playlist_id}` }, { quiet: true });
    if (seq !== probeSeq) return;
    state.playlistProbe = data.ok ? data : { type: "error", error: data.error };
    if (data.ok) state.selected = new Set(data.entries.map((e) => e.id));
  }
  renderPreview();
  renderQuality();
}

function currentPlaylist() {
  if (state.probe?.type === "playlist") return state.probe;
  if (state.playlistMode && state.playlistProbe?.type === "playlist") return state.playlistProbe;
  return null;
}

function arabicChip(p) {
  if (!p.subtitles_supported) return `<span class="chip">${icon("cc")}${esc(t("no_subs_site"))}</span>`;
  const g = state.status?.gemini;
  const geminiFirst = state.settings.translation_order === "gemini_first";
  if (p.arabic?.manual) return `<span class="chip ok">${icon("check")}${esc(t("ar_manual"))}</span>`;
  let key;
  if (geminiFirst && g) key = "ar_gemini";
  else if (p.arabic?.auto) key = "ar_youtube";
  else key = g ? "ar_gemini" : "ar_google";
  return `<span class="chip info">${icon("cc")}${esc(t(key))}</span>`;
}

function renderPreview() {
  const box = $("preview");
  const p = state.probe;
  if (!p) {
    box.innerHTML = `<div class="pv-empty"><span>${esc(t("supported"))}</span>
      <span>${icon("youtube")}YouTube</span><span>${icon("instagram")}Instagram</span>
      <span>${icon("hash")}X / Twitter</span><span>${esc(t("any_site"))}</span></div>`;
    renderDownloadButton();
    return;
  }
  if (p.type === "loading") {
    box.innerHTML = `<div class="pv"><div class="pv-thumb skel"></div><div class="pv-main">
      <div class="skel skel-line" style="width:70%"></div><div class="skel skel-line" style="width:40%"></div>
      <div class="hint" style="margin:6px 0 0">${esc(t("probing"))}</div></div></div>`;
    renderDownloadButton();
    return;
  }
  if (p.type === "batch") {
    const kinds = { youtube: "youtube", instagram: "instagram", x: "hash" };
    box.innerHTML = `<div class="pv"><div class="pv-main">
      <div class="pv-title">${icon("list")} ${esc(t("batch_title", { n: p.urls.length }))}</div>
      <div class="batch">${p.urls.map((u) => {
        const k = /instagram\.com/i.test(u) ? "instagram" : /(x|twitter)\.com/i.test(u) ? "x" : /youtu/i.test(u) ? "youtube" : "";
        return `<div class="batch-row">${icon(kinds[k] || "link")}<code>${esc(u)}</code></div>`;
      }).join("")}</div></div></div>`;
    renderDownloadButton();
    return;
  }
  if (p.type === "error") {
    const xExtra = p.kind === "x"
      ? `<div class="pv-note">${esc(t("x_hint"))}<button class="btn sm" type="button" data-act="thread">${icon("hash")}${esc(t("extract_thread"))}</button></div>` : "";
    box.innerHTML = `<div class="pv error">${icon("alert")}<div class="pv-main">
      <div class="pv-title">${esc(t("probe_failed"))}</div><div class="pv-meta" dir="auto">${esc(p.error || "")}</div>${xExtra}</div></div>`;
    bindPreviewActions(box);
    renderDownloadButton();
    return;
  }
  if (p.type === "instagram") {
    box.innerHTML = `<div class="pv"><div class="pv-thumb">${icon("instagram")}</div><div class="pv-main">
      <div class="pv-title">${esc(t("instagram_title"))}</div>
      <div class="pv-meta" dir="ltr">${esc(p.url)}</div>
      ${state.status?.instagram_cookies ? "" : `<div class="hint" style="margin:0">${esc(t("instagram_hint"))}</div>`}
    </div></div>`;
    renderDownloadButton();
    return;
  }

  const pl = currentPlaylist();
  if (pl) {
    box.innerHTML = (p.type === "video" ? playlistToggle(p) : "") + playlistCard(pl);
  } else if (state.playlistMode && state.playlistProbe) {
    const pp = state.playlistProbe;
    box.innerHTML = playlistToggle(p) + (pp.type === "loading"
      ? `<div class="pv"><div class="pv-main"><div class="skel skel-line" style="width:60%"></div><div class="hint">${esc(t("probing"))}</div></div></div>`
      : `<div class="pv error">${icon("alert")}<div class="pv-main"><div class="pv-meta">${esc(pp.error || "")}</div></div></div>`);
  } else {
    box.innerHTML = videoCard(p);
  }
  bindPreviewActions(box);
  renderDownloadButton();
}

function videoCard(p) {
  const meta = [
    p.channel ? esc(p.channel) : "",
    p.view_count ? esc(t("views", { n: fmtNumber(p.view_count) })) : "",
    p.upload_date ? esc(fmtUploadDate(p.upload_date)) : "",
    p.count ? esc(t("n_videos", { n: p.count })) : "",
  ].filter(Boolean).join('<span class="dot">·</span>');
  const chips = [
    arabicChip(p),
    p.chapters ? `<span class="chip">${icon("list")}${esc(t("chapters_n", { n: p.chapters }))}</span>` : "",
  ].join("");
  const note = p.playlist_id
    ? `<div class="pv-note">${icon("layers")}<span>${esc(t("in_playlist"))}</span>
       <span class="seg"><button type="button" class="on" data-act="pl-off">${esc(t("this_video"))}</button>
       <button type="button" data-act="pl-on">${esc(t("whole_playlist"))}</button></span></div>` : "";
  const xNote = p.kind === "x"
    ? `<div class="pv-note">${esc(t("x_hint"))}<button class="btn sm" type="button" data-act="thread">${icon("hash")}${esc(t("extract_thread"))}</button></div>` : "";
  return `<div class="pv">
    ${thumbBlock(p.thumbnail, p.duration)}
    <div class="pv-main">
      <div class="pv-title" dir="auto"><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a></div>
      <div class="pv-meta" dir="auto">${meta}</div>
      <div class="chips">${chips}</div>
      ${note}${xNote}
    </div></div>`;
}

function thumbBlock(src, duration) {
  const img = src ? `<img src="${esc(src)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : "";
  const time = duration ? `<span class="badge-time">${fmtDuration(duration)}</span>` : "";
  return `<div class="pv-thumb">${img || icon("film")}${time}</div>`;
}

function playlistToggle(p) {
  return `<div class="pv-note" style="margin:0 0 10px">${icon("layers")}<span>${esc(t("in_playlist"))}</span>
    <span class="seg"><button type="button" data-act="pl-off">${esc(t("this_video"))}</button>
    <button type="button" class="on" data-act="pl-on">${esc(t("whole_playlist"))}</button></span></div>`;
}

function playlistCard(pl) {
  const n = pl.entries.filter((e) => state.selected.has(e.id)).length;
  const meta = [
    pl.channel ? esc(pl.channel) : "",
    esc(t("n_videos", { n: pl.count })),
    pl.duration ? fmtDuration(pl.duration) : "",
  ].filter(Boolean).join('<span class="dot">·</span>');
  const items = pl.entries.map((e, i) => `
    <label class="pl-item ${state.selected.has(e.id) ? "" : "off"}">
      <input type="checkbox" data-id="${esc(e.id)}" ${state.selected.has(e.id) ? "checked" : ""}>
      <span class="idx">${i + 1}</span>
      <span class="t" dir="auto" title="${esc(e.title)}">${esc(e.title)}</span>
      <span class="d">${e.duration ? fmtDuration(e.duration) : ""}</span>
    </label>`).join("");
  return `<div class="pv" style="flex-direction:column">
    <div style="display:flex;gap:16px">
      ${thumbBlock(pl.thumbnail, null)}
      <div class="pv-main">
        <div class="pv-title" dir="auto"><a href="${esc(pl.url)}" target="_blank" rel="noopener">${icon("layers")} ${esc(pl.title)}</a></div>
        <div class="pv-meta" dir="auto">${meta}</div>
        <div class="pl-tools">
          <button class="btn ghost sm" type="button" data-act="sel-all">${esc(t("select_all"))}</button>
          <button class="btn ghost sm" type="button" data-act="sel-none">${esc(t("select_none"))}</button>
          <input type="text" class="select-sm" id="plRange" dir="ltr" placeholder="${esc(t("select_range"))}" style="width:150px">
          <button class="btn ghost sm" type="button" data-act="sel-range">${esc(t("apply"))}</button>
          <span id="plCount">${esc(t("selected_n", { n, total: pl.count }))}</span>
        </div>
      </div>
    </div>
    <div class="pl-list">${items}</div>
  </div>`;
}

function parseRange(text, max) {
  const out = new Set();
  for (const part of text.split(/[,\s،]+/).filter(Boolean)) {
    const m = part.match(/^(\d+)(?:\s*[-–]\s*(\d+))?$/);
    if (!m) continue;
    let a = +m[1], b = m[2] ? +m[2] : a;
    if (a > b) [a, b] = [b, a];
    for (let i = Math.max(1, a); i <= Math.min(max, b); i++) out.add(i - 1);
  }
  return out;
}

function updatePlaylistCount() {
  const pl = currentPlaylist();
  if (!pl) return;
  const n = pl.entries.filter((e) => state.selected.has(e.id)).length;
  const el = $("plCount");
  if (el) el.textContent = t("selected_n", { n, total: pl.count });
  renderDownloadButton();
}

function bindPreviewActions(box) {
  box.querySelectorAll("[data-act]").forEach((el) =>
    el.addEventListener("click", () => {
      const pl = currentPlaylist();
      switch (el.dataset.act) {
        case "pl-on": setPlaylistMode(true); break;
        case "pl-off": setPlaylistMode(false); break;
        case "thread": extractThread(state.probeUrl || urlsFromBox()[0]); break;
        case "sel-all": pl.entries.forEach((e) => state.selected.add(e.id)); renderPreview(); break;
        case "sel-none": state.selected.clear(); renderPreview(); break;
        case "sel-range": {
          const idx = parseRange($("plRange").value, pl.entries.length);
          if (!idx.size) return;
          state.selected = new Set(pl.entries.filter((_, i) => idx.has(i)).map((e) => e.id));
          renderPreview();
          break;
        }
      }
    })
  );
  box.querySelectorAll(".pl-item input").forEach((cb) =>
    cb.addEventListener("change", () => {
      cb.checked ? state.selected.add(cb.dataset.id) : state.selected.delete(cb.dataset.id);
      cb.closest(".pl-item").classList.toggle("off", !cb.checked);
      updatePlaylistCount();
    })
  );
  const range = $("plRange");
  if (range) range.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); box.querySelector('[data-act="sel-range"]').click(); }
  });
}

function renderQuality() {
  const s = state.status;
  if (!s) return;
  const p = state.probe;
  const sizes = p && p.type === "video" && !state.playlistMode ? p.sizes || {} : {};
  if (!state.quality) state.quality = state.settings.default_quality || "2";
  $("qualityGrid").innerHTML = s.qualities.map((q) => {
    const audio = q.key === "6";
    const main = audio ? t("q_audio") : QUALITY_MAIN[q.key] || q.label;
    const sub = audio ? t("q_audio_sub") : t("q_sub_" + q.key);
    const size = sizes[q.key] && sizes[q.key] !== "?" ? sizes[q.key] : "";
    return `<button type="button" class="q-btn ${state.quality === q.key ? "on" : ""}" data-q="${q.key}">
      <span class="q-main">${esc(main)}</span><span class="q-sub">${esc(sub)}</span><span class="q-size">${esc(size)}</span></button>`;
  }).join("");
  $("qualityGrid").querySelectorAll(".q-btn").forEach((b) =>
    b.addEventListener("click", () => { state.quality = b.dataset.q; renderQuality(); })
  );
  // Option visibility for what's being downloaded
  const audio = state.quality === "6";
  const kind = p?.kind;
  const ytOnly = !p || p.type === "batch" || kind === "youtube" || p.type === "playlist" || p.type === "loading";
  $("dlSubModeWrap").classList.toggle("hidden", !ytOnly);
  $("dlEmbedWrap").classList.toggle("hidden", audio || !ytOnly);
  $("dlTranscriptWrap").classList.toggle("hidden", audio || !(p && p.type === "video" && kind === "youtube" && !state.playlistMode));
  renderDownloadButton();
}

function renderDownloadButton() {
  const p = state.probe;
  const pl = currentPlaylist();
  let label;
  if (pl) label = t("download_playlist_n", { n: pl.entries.filter((e) => state.selected.has(e.id)).length });
  else if (p?.type === "batch") label = t("queue_n_links", { n: p.urls.length });
  else label = state.busy ? t("add_to_queue") : t("start_download");
  $("btnDownloadLabel").textContent = label;
  $("dlHint").textContent = state.busy && (pl || p?.type === "batch") ? t("add_to_queue") : "";
}

async function startDownload() {
  const urls = urlsFromBox();
  if (!urls.length) { toast(t("enter_url"), "warn"); urlBox.focus(); return; }
  const body = {
    urls,
    quality: state.quality,
    subtitle_mode: $("dlSubMode").value,
    embed: $("dlEmbed").checked,
    with_transcript: !$("dlTranscriptWrap").classList.contains("hidden") && $("dlTranscript").checked,
  };
  const pl = currentPlaylist();
  if (pl) {
    const ids = pl.entries.map((e) => e.id);
    const picked = ids.filter((id) => state.selected.has(id));
    if (!picked.length) { toast(t("select_one"), "warn"); return; }
    body.urls = [pl.url];
    body.playlist = true;
    if (picked.length < ids.length) body.items = picked;
  } else if (state.playlistMode) {
    return;  // playlist still loading
  }
  const btn = $("btnDownload");
  btn.disabled = true;
  const r = await post("/api/download", body);
  btn.disabled = false;
  if (!r.ok) return;
  toast(r.jobs > 1 ? t("queued_n", { n: r.jobs }) : r.status === "queued" ? t("added_to_queue") : t("download_started"), "success");
  urlBox.value = "";
  autoGrow();
  state.probe = null; state.probeUrl = ""; state.playlistMode = false; state.playlistProbe = null;
  renderPreview();
  renderQuality();
}
$("btnDownload").addEventListener("click", startDownload);

async function extractThread(url) {
  if (!url) return toast(t("enter_url"), "warn");
  const r = await post("/api/tweet", { url });
  if (r.ok) toast(r.status === "queued" ? t("added_to_queue") : t("download_started"), "success");
}

/* ── history rows (shared by Download → Recent and History) ── */
const KIND_ICON = { video: "film", playlist: "layers", transcript: "text", summary: "sparkle", subtitle: "cc", tweet: "hash", instagram: "instagram" };
const RETRYABLE = new Set(["video", "playlist", "transcript", "tweet", "instagram"]);

function firstUrl(u) { return (u || "").split("|")[0]; }

function historyRow(e, i, compact = false) {
  const link = firstUrl(e.url);
  const linkBtn = link.startsWith("http")
    ? `<a class="icon-btn" href="${esc(link)}" target="_blank" rel="noopener" title="${esc(t("open_link"))}">${icon("external")}</a>` : "";
  const retry = !compact && RETRYABLE.has(e.kind)
    ? `<button class="icon-btn" type="button" data-retry="${i}" title="${esc(e.status === "success" ? t("again") : t("retry"))}">${icon("refresh")}</button>` : "";
  return `
    <div class="card">
      <div class="card-main">
        <div class="card-title"><span class="kind-tag">${esc(t("kind_" + e.kind))}</span><span class="tt" dir="auto" title="${esc(e.title)}">${esc(e.title || "(untitled)")}</span></div>
        <div class="card-sub" dir="auto">${esc(fmtWhen(e.time))}${!compact && e.detail ? " · " + esc(e.detail) : ""}</div>
      </div>
      <div class="card-actions">${retry}${linkBtn}<span class="status-dot ${esc(e.status)}" title="${esc(t("status_" + e.status))}"></span></div>
    </div>`;
}

async function loadRecent() {
  const { entries = [] } = await get("/api/history", { quiet: true });
  state.history = entries;
  const box = $("recentList");
  box.innerHTML = entries.length
    ? entries.slice(0, 5).map((e, i) => historyRow(e, i, true)).join("")
    : `<p class="empty">${icon("clock")}${esc(t("hist_empty"))}</p>`;
}

/* ════════════════════════════════════════════
   Library
   ════════════════════════════════════════════ */
async function loadLibrary() {
  const d = await get("/api/library", { quiet: true });
  if (!d || d.ok === false || !d.items) return;
  state.library = d;
  renderLibrary();
}

function libraryFiltered() {
  const d = state.library;
  if (!d) return [];
  const q = $("libSearch").value.trim().toLowerCase();
  const f = $("libFilter").value;
  return d.items.filter((it) => {
    if (q && !(it.title.toLowerCase().includes(q) || it.folder.toLowerCase().includes(q))) return false;
    if (f === "missing") return !it.is_audio && !it.has_arabic;
    if (f === "video") return !it.is_audio;
    if (f === "audio") return it.is_audio;
    return true;
  });
}

function subtitleChips(it) {
  if (it.is_audio) return `<span class="chip">${icon("music")}${esc(it.ext.toUpperCase())}</span>`;
  if (!it.subtitles.length) return `<span class="chip warn">${icon("cc")}${esc(t("no_subtitle"))}</span>`;
  const seen = new Set();
  return it.subtitles.filter((s) => {
    const key = s.is_arabic ? "ar" : (s.lang || "").split("-")[0];
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).map((s) => {
    const name = s.is_arabic ? "AR" : (s.lang || "?").split("-")[0].toUpperCase();
    const src = s.source ? ` · ${shortSource(s.source)}` : "";
    return `<span class="chip ${s.is_arabic ? "ok" : ""}" title="${esc(s.source || s.lang)}">${icon("cc")}${esc(name + src)}</span>`;
  }).join("");
}

function renderLibrary() {
  const d = state.library;
  if (!d) return;
  const items = libraryFiltered();
  $("libStats").textContent = t("lib_stats", { n: d.count, size: fmtBytes(d.total_size) });

  const left = d.leftovers || {};
  const banner = $("leftoverBanner");
  if (left.junk_bytes > 0 || left.unfinished_count > 0) {
    const parts = [];
    if (left.junk_bytes > 0) parts.push(t("leftovers", { size: fmtBytes(left.junk_bytes) }));
    if (left.unfinished_count > 0) parts.push(t("leftovers_unfinished", { n: left.unfinished_count, size: fmtBytes(left.unfinished_bytes) }));
    banner.innerHTML = `${icon("trash")}<span>${esc(parts.join(" "))}</span><span class="grow"></span>
      <button class="btn sm" type="button" id="btnCleanup">${esc(t("review_cleanup"))}</button>`;
    banner.classList.remove("hidden");
    $("btnCleanup").addEventListener("click", openCleanup);
  } else banner.classList.add("hidden");

  const box = $("libList");
  if (!items.length) {
    box.innerHTML = `<p class="empty">${icon("film")}${esc(d.count ? t("lib_no_match") : t("lib_empty"))}</p>`;
    return;
  }
  box.innerHTML = items.map((it, i) => {
    const thumb = it.thumbnail
      ? `<img src="${esc(it.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : "";
    const meta = [it.folder || t("root_folder"), fmtBytes(it.size), fmtWhen(it.mtime), it.ext.toUpperCase()];
    return `
      <div class="lib-row">
        <button class="lib-thumb" type="button" data-play="${i}" title="${esc(t("play"))}">${thumb || icon(it.is_audio ? "music" : "film")}
          <span class="play-hover">${icon("play")}</span></button>
        <div class="lib-main">
          <div class="lib-title" dir="auto" title="${esc(it.title)}">${esc(it.title)}</div>
          <div class="lib-meta" dir="auto">${meta.map(esc).join(" · ")}</div>
          <div class="chips">${subtitleChips(it)}</div>
        </div>
        <div class="lib-actions">
          <button class="btn soft sm" type="button" data-play="${i}">${icon("play")}${esc(t("play"))}</button>
          <button class="icon-btn" type="button" data-folder="${i}" title="${esc(t("show_in_folder"))}">${icon("folder")}</button>
          <div class="menu"><button class="icon-btn" type="button" data-menu="${i}" title="${esc(t("m_more"))}">${icon("more")}</button></div>
        </div>
      </div>`;
  }).join("");

  box.querySelectorAll("[data-play]").forEach((b) => b.addEventListener("click", () => openPlayer(items[+b.dataset.play])));
  box.querySelectorAll("[data-folder]").forEach((b) => b.addEventListener("click", () => openFolder(items[+b.dataset.folder].path)));
  box.querySelectorAll("[data-menu]").forEach((b) => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    toggleMenu(b.parentElement, items[+b.dataset.menu]);
  }));
}

function closeMenus() { $$(".menu.open").forEach((m) => { m.classList.remove("open", "up"); m.querySelector(".menu-pop")?.remove(); }); }
document.addEventListener("click", (e) => { if (!e.target.closest(".menu-pop")) closeMenus(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });

function toggleMenu(menu, it) {
  const wasOpen = menu.classList.contains("open");
  closeMenus();
  if (wasOpen) return;
  const vid = it.video_id;
  const yt = vid ? `https://www.youtube.com/watch?v=${vid}` : null;
  const entries = [];
  if (!it.is_audio) {
    entries.push(`<div class="menu-label">${esc(t("m_subtitles"))}</div>`);
    if (vid) {
      entries.push(menuItem("sub-auto", "cc", it.has_arabic ? t("m_refetch_ar") : t("m_get_ar")));
      entries.push(menuItem("sub-gemini", "sparkle", t("m_gemini")));
      entries.push(menuItem("sub-youtube", "youtube", t("m_youtube")));
      entries.push(menuItem("sub-google", "globe", t("m_google")));
      entries.push(menuItem("sub-english", "cc", t("m_english")));
    } else {
      entries.push(`<div class="menu-label" style="text-transform:none;letter-spacing:0">${esc(t("no_id"))}</div>`);
    }
    if (it.subtitles.length) entries.push(menuItem("embed", "layers", t("m_embed")));
  }
  if (yt) {
    entries.push("<hr>");
    entries.push(menuItem("transcript", "text", t("m_transcript")));
    entries.push(`<a href="${esc(yt)}" target="_blank" rel="noopener">${icon("external")}${esc(t("m_open_yt"))}</a>`);
  }
  const pop = document.createElement("div");
  pop.className = "menu-pop";
  pop.innerHTML = entries.join("");
  menu.appendChild(pop);
  menu.classList.add("open");
  const rect = pop.getBoundingClientRect();
  if (rect.bottom > window.innerHeight - 8) menu.classList.add("up");
  pop.querySelectorAll("[data-mi]").forEach((b) => b.addEventListener("click", () => {
    closeMenus();
    runLibraryAction(b.dataset.mi, it);
  }));
}
function menuItem(action, ic, label) {
  return `<button type="button" data-mi="${action}">${icon(ic)}<span>${esc(label)}</span></button>`;
}

async function runLibraryAction(action, it) {
  let r;
  if (action.startsWith("sub-")) r = await post("/api/fetch-subtitle", { path: it.path, engine: action.slice(4) });
  else if (action === "embed") r = await post("/api/embed", { path: it.path });
  else if (action === "transcript") r = await post("/api/transcript", { url: `https://www.youtube.com/watch?v=${it.video_id}` });
  if (r?.ok) toast(r.status === "queued" ? t("added_to_queue") : t("download_started"), "success");
}

let libSearchTimer;
$("libSearch").addEventListener("input", () => { clearTimeout(libSearchTimer); libSearchTimer = setTimeout(renderLibrary, 120); });
$("libFilter").addEventListener("change", renderLibrary);
$("btnLibRefresh").addEventListener("click", loadLibrary);
$("btnOpenRoot").addEventListener("click", () => openFolder());

/* ── cleanup ── */
async function openCleanup() {
  const d = await get("/api/cleanup");
  if (!d || d.ok === false) return;
  const body = $("cleanupBody");
  const list = (arr) => `<div class="cleanup-list">${arr.map((e) =>
    `<div><span title="${esc(e.name)}">${esc(e.name)}</span><span>${fmtBytes(e.size)}</span></div>`).join("")}</div>`;
  body.innerHTML = (d.junk.length ? `<p style="margin:0">${esc(t("cleanup_intro"))}</p>${list(d.junk)}` : `<p>${esc(t("cleanup_none"))}</p>`) +
    (d.unfinished.length ? `<label class="switch" style="margin-top:6px"><input type="checkbox" id="cleanupUnfinished"><span class="track"></span>
      <span>${esc(t("cleanup_unfinished", { n: d.unfinished.length, size: fmtBytes(d.unfinished_bytes) }))}</span></label>
      <div id="cleanupUnfinishedList" class="hidden">${list(d.unfinished)}</div>` : "");
  const update = () => {
    const all = $("cleanupUnfinished")?.checked;
    $("cleanupUnfinishedList")?.classList.toggle("hidden", !all);
    const n = d.junk.length + (all ? d.unfinished.length : 0);
    const size = d.junk_bytes + (all ? d.unfinished_bytes : 0);
    $("cleanupConfirmLabel").textContent = t("cleanup_delete_n", { n, size: fmtBytes(size) });
    $("cleanupConfirm").disabled = !n;
  };
  $("cleanupUnfinished")?.addEventListener("change", update);
  update();
  $("cleanupDlg").showModal();
}
$("cleanupConfirm").addEventListener("click", async () => {
  const r = await post("/api/cleanup", { include_unfinished: !!$("cleanupUnfinished")?.checked });
  $("cleanupDlg").close();
  if (r.ok) toast(t("cleaned", { size: fmtBytes(r.freed) }), "success");
  loadLibrary();
});

/* ── player ── */
const video = $("playerVideo");
let playerItem = null;

async function playPath(path) {
  if (!state.library) await loadLibrary();
  const it = state.library?.items.find((x) => x.path === path);
  if (it) openPlayer(it);
}

function openPlayer(it) {
  playerItem = it;
  $("playerTitle").textContent = it.title;
  $("playerError").classList.add("hidden");
  video.pause();
  video.innerHTML = "";
  video.removeAttribute("src");
  video.poster = it.is_audio && it.thumbnail ? it.thumbnail : "";
  const subs = it.is_audio ? [] : it.subtitles;
  subs.forEach((s, i) => {
    const tr = document.createElement("track");
    tr.kind = "subtitles";
    tr.label = langName(s.lang) + (s.source ? ` · ${shortSource(s.source)}` : "");
    tr.srclang = (s.lang || "und").split("-")[0];
    tr.src = `/api/subtitle?path=${encodeURIComponent(s.path)}`;
    if (i === 0) tr.default = true;
    video.appendChild(tr);
  });
  $("playerSubs").innerHTML = `<option value="-1">${esc(t("subs_off"))}</option>` +
    subs.map((s, i) => `<option value="${i}" ${i === 0 ? "selected" : ""}>${esc(langName(s.lang) + (s.source ? " · " + shortSource(s.source) : ""))}</option>`).join("");
  $("playerSubs").closest(".field").classList.toggle("hidden", !subs.length);
  video.src = `/api/media?path=${encodeURIComponent(it.path)}`;
  $("playerDlg").showModal();
  video.play().catch(() => {});
}
video.addEventListener("loadedmetadata", () => applyTrack(+$("playerSubs").value));
video.addEventListener("error", () => {
  if (!video.getAttribute("src")) return;
  $("playerError").textContent = t("cant_play");
  $("playerError").classList.remove("hidden");
});
function applyTrack(index) {
  [...video.textTracks].forEach((tt, i) => { tt.mode = i === index ? "showing" : "disabled"; });
}
$("playerSubs").addEventListener("change", () => applyTrack(+$("playerSubs").value));
$$("#cueSize button").forEach((b) => b.addEventListener("click", () => {
  $$("#cueSize button").forEach((x) => x.classList.toggle("on", x === b));
  video.className = "cue-" + b.dataset.size;
  store("cue", b.dataset.size);
}));
(() => {
  const size = store("cue");
  if (size) $$("#cueSize button").forEach((b) => b.dataset.size === size && b.click());
})();
$("playerFolder").addEventListener("click", () => playerItem && openFolder(playerItem.path));
$("playerDlg").addEventListener("close", () => {
  // Release the file — on Windows an open handle would block embedding
  // subtitles into it or cleaning up afterwards.
  video.pause();
  video.removeAttribute("src");
  video.innerHTML = "";
  video.load();
});

$$("dialog [data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));
$$("dialog").forEach((d) => d.addEventListener("click", (e) => { if (e.target === d) d.close(); }));

/* ════════════════════════════════════════════
   Transcripts
   ════════════════════════════════════════════ */
async function loadTranscripts() {
  const d = await get("/api/transcripts", { quiet: true });
  if (!d || !d.items) return;
  state.transcripts = d.items;
  renderTranscripts();
}

function renderTranscripts() {
  const box = $("trList");
  if (!state.transcripts.length) {
    box.innerHTML = `<p class="empty">${icon("text")}${esc(t("tr_empty"))}</p>`;
    return;
  }
  box.innerHTML = state.transcripts.map((tr, i) => {
    const kind = tr.kind === "tweet" ? t("kind_tweet_short") : t("kind_transcript");
    const sums = Object.keys(tr.summaries || {}).map((l) =>
      `<span class="chip ok">${icon("sparkle")}${esc(l === "ar" ? t("summary_ar") : t("summary_en"))}</span>`).join("");
    const sub = [fmtWhen(tr.mtime), tr.words ? t("words_n", { n: tr.words.toLocaleString(locale()) }) : ""].filter(Boolean).join(" · ");
    return `
      <div class="card">
        <div class="card-main">
          <div class="card-title"><span class="kind-tag">${esc(kind)}</span><span class="tt" dir="auto" title="${esc(tr.title)}">${esc(tr.title)}</span></div>
          <div class="card-sub"><span>${esc(sub)}</span> <span class="chips" style="display:inline-flex">${sums}</span></div>
        </div>
        <div class="card-actions">
          <button class="btn soft sm" type="button" data-view="${i}">${icon("text")}${esc(t("view"))}</button>
          <button class="icon-btn" type="button" data-copy="${i}" title="${esc(t("copy"))}">${icon("copy")}</button>
          <button class="icon-btn" type="button" data-sum="${i}" title="${esc(t("summarize"))}">${icon("sparkle")}</button>
          <button class="icon-btn" type="button" data-folder="${i}" title="${esc(t("show_in_folder"))}">${icon("folder")}</button>
        </div>
      </div>`;
  }).join("");
  const items = state.transcripts;
  box.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => openText(items[+b.dataset.view].path)));
  box.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    copyText(await fetchText(items[+b.dataset.copy].path));
  }));
  box.querySelectorAll("[data-sum]").forEach((b) => b.addEventListener("click", () => summarize(items[+b.dataset.sum].path)));
  box.querySelectorAll("[data-folder]").forEach((b) => b.addEventListener("click", () => openFolder(items[+b.dataset.folder].path)));
}

async function fetchText(path) {
  const res = await fetch(`/api/text?path=${encodeURIComponent(path)}`);
  return res.ok ? res.text() : "";
}

async function summarize(path, sumLang) {
  if (!state.status?.gemini) return toast(t("needs_gemini"), "warn");
  const r = await post("/api/summarize", { path, lang: sumLang || state.settings.summary_lang || "ar" });
  if (r.ok) toast(t("summary_started"), "info");
}

$("btnTranscript").addEventListener("click", async () => {
  const url = $("exUrl").value.trim();
  if (!url) return toast(t("enter_url"), "warn");
  const r = await post("/api/transcript", { url, lang: $("exLang").value, timestamps: $("exTimestamps").checked });
  if (r.ok) toast(r.status === "queued" ? t("added_to_queue") : t("download_started"), "success");
});
$("btnTweet").addEventListener("click", () => extractThread($("exUrl").value.trim()));
$("exUrl").addEventListener("keydown", (e) => { if (e.key === "Enter") $("btnTranscript").click(); });
$("exUrl").addEventListener("input", fixLinkInputDir);
$("btnTrRefresh").addEventListener("click", loadTranscripts);

/* ── text viewer ── */
function renderMarkdown(md) {
  const lines = esc(md).split(/\r?\n/);
  let html = "", inList = false;
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  for (const raw of lines) {
    const line = raw.trimEnd();
    const h = line.match(/^#{1,4}\s+(.*)$/);
    const li = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (li) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inline(li[1])}</li>`;
      continue;
    }
    if (inList) { html += "</ul>"; inList = false; }
    if (h) html += `<h3>${inline(h[1])}</h3>`;
    else if (line.trim()) html += `<p>${inline(line)}</p>`;
  }
  if (inList) html += "</ul>";
  return html;
}

async function openText(path, show) {
  if (!state.transcripts.length || !state.transcripts.find((x) => x.path === path)) await loadTranscripts();
  const tr = state.transcripts.find((x) => x.path === path) || { path, title: path.split("/").pop(), summaries: {} };
  const tabs = [{ id: "transcript", label: t("transcript"), path: tr.path, md: false }];
  for (const [l, p] of Object.entries(tr.summaries || {})) tabs.push({ id: "sum-" + l, label: l === "ar" ? t("summary_ar") : t("summary_en"), path: p, md: true, lang: l });
  const current = tabs.find((x) => x.path === show) || tabs[0];
  state.textView = { path: tr.path, title: tr.title, tabs, current: current.id, text: "" };
  $("textTitle").textContent = tr.title;
  $("textTabs").innerHTML = tabs.length > 1
    ? tabs.map((x) => `<button type="button" data-tt="${x.id}" class="${x.id === current.id ? "on" : ""}">${esc(x.label)}</button>`).join("") : "";
  $("textTabs").querySelectorAll("[data-tt]").forEach((b) => b.addEventListener("click", () => showTextTab(b.dataset.tt)));
  if (!$("textDlg").open) $("textDlg").showModal();
  showTextTab(current.id);
}

async function showTextTab(id) {
  const v = state.textView;
  const tab = v.tabs.find((x) => x.id === id);
  v.current = id;
  $("textTabs").querySelectorAll("[data-tt]").forEach((b) => b.classList.toggle("on", b.dataset.tt === id));
  const body = $("textBody");
  body.innerHTML = `<div class="skel skel-line" style="width:80%"></div><div class="skel skel-line" style="width:60%"></div>`;
  const text = await fetchText(tab.path);
  v.text = text;
  body.classList.toggle("md", tab.md);
  body.innerHTML = tab.md ? renderMarkdown(text) : `<pre>${esc(text)}</pre>`;
  body.scrollTop = 0;
  const words = text.split(/\s+/).filter(Boolean).length;
  $("textMeta").textContent = t("words_n", { n: words.toLocaleString(locale()) });
  const sumLang = state.settings.summary_lang || "ar";
  $("textSummarize").querySelector("span").textContent =
    t("summarize_in", { lang: sumLang === "ar" ? (lang === "ar" ? "عربية" : "Arabic") : (lang === "ar" ? "إنكليزية" : "English") });
}
$("textCopy").addEventListener("click", () => state.textView && copyText(state.textView.text));
$("textSummarize").addEventListener("click", () => state.textView && summarize(state.textView.path));
$("textFolder").addEventListener("click", () => {
  const v = state.textView;
  if (v) openFolder(v.tabs.find((x) => x.id === v.current)?.path || v.path);
});

/* ════════════════════════════════════════════
   Resume
   ════════════════════════════════════════════ */
async function loadResume() {
  const d = await get("/api/saved-progress", { quiet: true });
  if (!d || !d.playlists) return;
  state.resume = d;
  setResumeBadge(d.playlists.length + d.singles.length);
  renderResume();
}
async function loadResumeBadge() {
  const d = await get("/api/saved-progress", { quiet: true });
  if (d && d.playlists) { state.resume = d; setResumeBadge(d.playlists.length + d.singles.length); }
}
function setResumeBadge(n) {
  const b = $("resumeBadge");
  b.textContent = n;
  b.classList.toggle("hidden", !n);
}

function renderResume() {
  const { playlists, singles } = state.resume;
  const box = $("resumeList");
  if (!playlists.length && !singles.length) {
    box.innerHTML = `<p class="empty">${icon("check")}${esc(t("resume_empty"))}</p>`;
    return;
  }
  const singleCards = singles.map((s, i) => `
    <div class="card resume-card"><div class="card-row">
      <div class="card-main">
        <div class="card-title">${icon("film")}<span class="tt" dir="auto">${esc(s.title)}</span></div>
        <div class="card-sub">${esc(s.quality_label)} · ${esc(t("stopped_mid"))}</div>
      </div>
      <div class="card-actions">
        <a class="icon-btn" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(t("open_link"))}">${icon("external")}</a>
        <button class="icon-btn" type="button" data-forget-single="${i}" title="${esc(t("forget"))}">${icon("trash")}</button>
        <button class="btn primary sm" type="button" data-resume-single="${i}">${icon("resume")}${esc(t("resume"))}</button>
      </div>
    </div></div>`).join("");

  const playlistCards = playlists.map((p, i) => {
    const total = p.total;
    const progress = total ? t("done_of", { done: p.done, total }) : t("done_n", { n: p.done });
    const pct = total ? Math.min(100, Math.round((p.done / total) * 100)) : 0;
    return `
    <div class="card resume-card"><div class="card-row">
      <div class="card-main">
        <div class="card-title">${icon("layers")}<span class="tt" dir="auto">${esc(p.title)}</span></div>
        <div class="card-sub">${esc(progress)} · ${esc(p.quality_label)}${p.selected ? " · " + esc(t("selected_only", { n: p.selected })) : ""}</div>
        ${total ? `<div class="mini-progress"><div style="width:${pct}%"></div></div>` : ""}
      </div>
      <div class="card-actions">
        <a class="icon-btn" href="${esc(p.url)}" target="_blank" rel="noopener" title="${esc(t("open_link"))}">${icon("external")}</a>
        <button class="icon-btn" type="button" data-forget="${i}" title="${esc(t("forget"))}">${icon("trash")}</button>
        <button class="btn ghost sm" type="button" data-expand="${i}">${icon("list")}${esc(t("videos"))}</button>
        <button class="btn primary sm" type="button" data-resume="${i}">${icon("resume")}${esc(t("resume"))}</button>
      </div>
    </div><div class="playlist-videos hidden" id="pv-${i}"></div></div>`;
  }).join("");

  box.innerHTML = singleCards + playlistCards;
  box.querySelectorAll("[data-resume]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    const r = await post("/api/resume", { url: playlists[+b.dataset.resume].url });
    if (r.ok) toast(r.status === "queued" ? t("added_to_queue") : t("download_started"), "success");
  }));
  box.querySelectorAll("[data-resume-single]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    const r = await post("/api/resume-single", { url: singles[+b.dataset.resumeSingle].url });
    if (r.ok) toast(r.status === "queued" ? t("added_to_queue") : t("download_started"), "success");
  }));
  box.querySelectorAll("[data-forget]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(t("forget_confirm"))) return;
    await post("/api/resume/forget", { url: playlists[+b.dataset.forget].url, type: "playlist" });
    loadResume();
  }));
  box.querySelectorAll("[data-forget-single]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(t("forget_confirm"))) return;
    await post("/api/resume/forget", { url: singles[+b.dataset.forgetSingle].url, type: "single" });
    loadResume();
  }));
  box.querySelectorAll("[data-expand]").forEach((b) => b.addEventListener("click", () => togglePlaylistVideos(b, playlists[+b.dataset.expand])));
}

async function togglePlaylistVideos(btn, p) {
  const target = $("pv-" + btn.dataset.expand);
  if (!target.classList.contains("hidden")) { target.classList.add("hidden"); return; }
  btn.disabled = true;
  const data = await get(`/api/playlist-detail?url=${encodeURIComponent(p.url)}&quality=${encodeURIComponent(p.quality)}`, { quiet: true });
  btn.disabled = false;
  target.innerHTML = !data.ok
    ? `<p class="empty">${esc(data.error || t("request_failed"))}</p>`
    : data.videos.map((v, i) => {
      const badge = v.downloaded ? ["ok", t("downloaded")] : v.selected ? ["warn", t("not_yet")] : ["", t("skipped")];
      return `<div class="video-row ${v.selected ? "" : "skipped"}">
        <span class="video-index">${i + 1}</span>
        <span class="video-title" dir="auto">${esc(v.title || v.video_id)}</span>
        <span class="chip ${badge[0]}">${esc(badge[1])}</span></div>`;
    }).join("");
  target.classList.remove("hidden");
}
$("btnRefreshResume").addEventListener("click", loadResume);

/* ════════════════════════════════════════════
   History
   ════════════════════════════════════════════ */
async function loadHistory() {
  const { entries = [] } = await get("/api/history", { quiet: true });
  state.history = entries;
  renderHistory();
}

function renderHistory() {
  const q = $("histSearch").value.trim().toLowerCase();
  const kind = $("histKind").value;
  const status = $("histStatus").value;
  const rows = state.history
    .map((e, i) => [e, i])
    .filter(([e]) => (kind === "all" || e.kind === kind) && (status === "all" || e.status === status) &&
      (!q || (e.title || "").toLowerCase().includes(q) || (e.url || "").toLowerCase().includes(q)));
  const box = $("historyList");
  box.innerHTML = rows.length
    ? rows.map(([e, i]) => historyRow(e, i)).join("")
    : `<p class="empty">${icon("clock")}${esc(t("hist_empty"))}</p>`;
  box.querySelectorAll("[data-retry]").forEach((b) => b.addEventListener("click", () => retryHistory(state.history[+b.dataset.retry])));
}

async function retryHistory(e) {
  const quality = e.quality || state.settings.default_quality;
  let r;
  if (e.kind === "video") r = await post("/api/download", { urls: [e.url], quality });
  else if (e.kind === "playlist") r = await post("/api/download", { urls: [e.url], playlist: true, quality });
  else if (e.kind === "transcript") r = await post("/api/transcript", { url: e.url });
  else if (e.kind === "tweet") r = await post("/api/tweet", { url: e.url });
  else if (e.kind === "instagram") r = await post("/api/instagram", { urls: e.url.split("|") });
  if (r?.ok) toast(r.status === "queued" ? t("added_to_queue") : t("download_started"), "success");
}

$("histSearch").addEventListener("input", renderHistory);
$("histKind").addEventListener("change", renderHistory);
$("histStatus").addEventListener("change", renderHistory);
$("btnClearHistory").addEventListener("click", async () => {
  if (!confirm(t("clear_history_confirm"))) return;
  await post("/api/history/clear", {});
  loadHistory();
});

/* ════════════════════════════════════════════
   Settings
   ════════════════════════════════════════════ */
const form = $("settingsForm");

function renderSettings() {
  const s = state.status;
  if (!s) return;
  const set = state.settings;
  $("setQuality").innerHTML = s.qualities.map((q) =>
    `<option value="${q.key}">${esc(q.key === "6" ? t("q_audio_sub") + " (MP3)" : q.label.replace(/\s+/g, " "))}</option>`).join("");
  for (const el of form.elements) {
    if (!el.name || !(el.name in set)) continue;
    if (el.type === "checkbox") el.checked = !!set[el.name];
    else if (el.type === "radio") el.checked = el.value === set[el.name];
    else el.value = set[el.name];
  }
  $("setNotify").checked = store("notify") === "1";
  $("setUiLang").value = lang;

  const row = (label, ok, value, missing) =>
    `<div class="k">${esc(label)}</div><div class="v ${ok ? "ok" : "no"}">${ok ? value : esc(missing)}</div>`;
  $("envInfo").innerHTML = [
    row(t("env_ffmpeg"), s.ffmpeg, `${icon("check")} <code>${esc(s.ffmpeg_path || "")}</code>`, t("env_ffmpeg_missing")),
    row(t("env_gemini"), s.gemini, `${icon("check")} ${esc(t("env_set"))}`, t("env_gemini_missing")),
    row(t("env_cookies"), s.cookies, `${icon("check")} ${esc(t("env_found"))}`, t("env_cookies_missing")),
    row(t("env_ig"), s.instagram_cookies, `${icon("check")} ${esc(t("env_found"))}`, t("env_ig_missing")),
    `<div class="k">${esc(t("env_folder"))}</div><div class="v"><code>${esc(s.download_dir)}</code>
      <button class="link-btn" type="button" id="envOpenFolder">${icon("folder")}${esc(t("open_folder"))}</button></div>`,
    `<div class="k">${esc(t("env_version"))}</div><div class="v"><code>${esc(s.version)}</code></div>`,
  ].join("");
  $("envOpenFolder").addEventListener("click", () => openFolder());
}

let saveTimer;
let unsaved = {};   // batched, so two quick changes don't cancel each other
async function saveSetting(changes) {
  const r = await post("/api/settings", changes);
  if (r.settings) {
    state.settings = r.settings;
    if (state.status) state.status.settings = r.settings;
  }
  if (r.ok) toast(t("saved"), "success");
  applyDownloadDefaults();
  renderQuality();
}
form.addEventListener("change", (e) => {
  const el = e.target;
  if (!el.name) return;
  let value = el.type === "checkbox" ? el.checked : el.value;
  if (el.type === "number") value = Number(el.value || 0);
  if (el.name === "default_quality") state.quality = value;
  unsaved[el.name] = value;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const changes = unsaved;
    unsaved = {};
    saveSetting(changes);
  }, el.type === "text" ? 400 : 0);
});
form.addEventListener("submit", (e) => e.preventDefault());
$("btnResetSettings").addEventListener("click", async () => {
  if (!confirm(t("reset_confirm"))) return;
  const d = await get("/api/settings");
  await saveSetting(d.defaults);
  state.quality = d.defaults.default_quality;
  renderSettings();
  renderQuality();
});
$("setUiLang").addEventListener("change", (e) => setLang(e.target.value));
$("setNotify").addEventListener("change", async (e) => {
  if (e.target.checked && "Notification" in window) {
    const perm = Notification.permission === "default" ? await Notification.requestPermission() : Notification.permission;
    if (perm !== "granted") {
      e.target.checked = false;
      toast(t("notify_denied"), "warn");
      return;
    }
  }
  store("notify", e.target.checked ? "1" : "0");
});
$("btnLang").addEventListener("click", () => setLang(lang === "ar" ? "en" : "ar"));

/* ════════════════════════════════════════════
   Boot
   ════════════════════════════════════════════ */
function renderAll() {
  renderPills();
  renderPreview();
  renderQuality();
  renderProgress();
  renderNow();
  renderQueue(state.queue);
  const tab = activeTab();
  if (tab === "library") renderLibrary();
  else if (tab === "transcripts") renderTranscripts();
  else if (tab === "resume") renderResume();
  else if (tab === "history") renderHistory();
  else if (tab === "settings") renderSettings();
  else loadRecent();
}

hydrateIcons();
applyLang();
renderPreview();
renderProgress();
connect();
loadResumeBadge();
showTab(location.hash.slice(1) || "download");
