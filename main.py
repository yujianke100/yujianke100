import feedparser
import os
import re
from datetime import datetime
from datetime import timedelta
from datetime import timezone
SHA_TZ = timezone(
    timedelta(hours=8),
    name='Asia/Shanghai',
)
def get_link_info(feed_url, num):
    result = ""
    feed = feedparser.parse(feed_url)
    feed_entries = feed["entries"]
    feed_entries_length = len(feed_entries)
    all_number = 0
    if(num > feed_entries_length):
        all_number = feed_entries_length
    else:
        all_number = num
    
    for entrie in feed_entries[0: all_number]:
        title = entrie["title"]
        link = entrie["link"]
        result = result + "\n" + "- [" + title + "](" + link + ")" + "\n"
    return result
    
def main():
    utc_now = datetime.utcnow().replace(tzinfo=timezone.utc)
    insert_info = "<!--BLOG_START-->\n## Recent Blog Posts\n *Update Time: "+ utc_now.astimezone(SHA_TZ).strftime('%Y-%m-%d %H:%M') + " (UTC+8) | Updated by Github Actions*\n" + get_link_info("https://feed.cnblogs.com/blog/u/769089/rss/", 5) + "<!--BLOG_END-->"
    print(insert_info)
    with open (os.path.join(os.getcwd(), "README.md"), 'r', encoding='utf-8') as f:
        readme_md_content = f.read()
    new_readme_md_content = re.sub(r'\<\!\-\-BLOG_START\-\-\>\n(.|\n)*\<\!\-\-BLOG_END\-\-\>', insert_info, readme_md_content)
    with open (os.path.join(os.getcwd(), "README.md"), 'w', encoding='utf-8') as f:
        f.write(new_readme_md_content)
main()
