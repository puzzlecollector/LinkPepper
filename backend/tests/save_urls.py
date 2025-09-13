import json
from pathlib import Path

urls = [
    "https://blogs.memphis.edu/padm3601/sample-page/",
    "https://www.hoomet.com/forums",
    "https://gotinstrumentals.com/front/beats/beatmixtape/noah-19688",
    "https://www.newreleasetoday.com/userprofile_artistsinglepost.php?review_id=16229",
    "https://www.welscamp-spanien.de/en-us/Gallery/emodule/741/eitem/301",
    "https://www.associationforjewishstudies.org/about-ajs/press-room/news-events/events-detail/2023/02/23/default-calendar/b'nai-binge-streaming-programming-list-for-february-22-by-laurie-baron-and-beth-chernoff",
    "http://www.izolacniskla.cz/forum-detail.php?dt_id=37168",
    "https://www.associationforjewishstudies.org/about-ajs/press-room/news-events/events-detail/2023/02/23/default-calendar/b'nai-binge-streaming-programming-list-for-february-22-by-laurie-baron-and-beth-chernoff",
    "https://denver.granicusideas.com/ideas/digital?page=4",
    "https://xiglute.com/forums/topic/74970/the-ultimate-guide-to-ibmseo/view/post_id/632800",
    "http://www.wymlbb.com/misc.php?mod=faq",
    "https://officerbg.com/shop/blog/greece-travel",
    "https://jedox4beginners.com/forum/canvas/kpi-card-formula-problem/",
    "https://www.nfunorge.org/Om-NFU/NFU-bloggen/samtykke-til-besvar/",
    "http://hydrology.irpi.cnr.it/stocha/",
    "https://bigsportsprize.dk/blog/wool-jackets",
    "https://www.southernfirst.com/personal/checking/personal-checking/clientfirst",
    "https://shop.kskids.com/index.php?route=journal3/blog/post&journal_blog_post_id=13",
]

Path("urls.json").write_text(
    json.dumps(urls, ensure_ascii=False, indent=2),
    encoding="utf-8"
)
