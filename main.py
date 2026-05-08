#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIニュースダッシュボード - メインスクリプト
自動的にRSSフィードからニュースを取得し、OpenAI APIで要約して
静的HTMLページを生成します。
"""

import json
import os
import sys
from datetime import datetime
from collections import defaultdict
import hashlib

import feedparser
import requests
from jinja2 import Environment, FileSystemLoader
from dotenv import load_dotenv
import openai


# .envファイルから環境変数を読み込む
load_dotenv()


class NewsAggregator:
    """
    RSSフィードからニュースを取得し、要約を生成するクラス
    """
    
    def __init__(self):
        """初期化 - OpenAI APIキーと設定を読み込む"""
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        if not self.openai_api_key:
            print("エラー: OPENAI_API_KEY が設定されていません")
            print(".env ファイルに OPENAI_API_KEY=xxxxx を追加してください")
            sys.exit(1)
        
        openai.api_key = self.openai_api_key
        self.client = openai.OpenAI(api_key=self.openai_api_key)
        self.news_items = []
        self.seen_hashes = set()  # 重複除去用
        
    def load_feeds(self, feeds_file='feeds.json'):
        """
        feeds.jsonからRSSフィードURLを読み込む
        
        Args:
            feeds_file (str): フィードファイルのパス
            
        Returns:
            dict: カテゴリ別フィードのリスト
        """
        try:
            with open(feeds_file, 'r', encoding='utf-8') as f:
                feeds = json.load(f)
            print(f"✓ {feeds_file} から {len(feeds)} カテゴリのフィードを読み込みました")
            return feeds
        except FileNotFoundError:
            print(f"エラー: {feeds_file} が見つかりません")
            sys.exit(1)
        except json.JSONDecodeError:
            print(f"エラー: {feeds_file} が正しいJSON形式ではありません")
            sys.exit(1)
    
    def fetch_feeds(self, feeds):
        """
        複数のRSSフィードから記事を取得
        
        Args:
            feeds (dict): カテゴリ別フィードのリスト
        """
        total_articles = 0
        
        for category, urls in feeds.items():
            print(f"\n📰 カテゴリ: {category}")
            
            for url in urls:
                try:
                    print(f"  取得中: {url[:50]}...")
                    feed = feedparser.parse(url, timeout=10)
                    
                    if feed.bozo:
                        print(f"  ⚠ 警告: {url} に問題があります: {feed.bozo_exception}")
                    
                    # フィードの最初の10記事を取得
                    for entry in feed.entries[:10]:
                        article = {
                            'title': entry.get('title', '無題'),
                            'link': entry.get('link', ''),
                            'description': entry.get('description') or entry.get('summary', '説明なし'),
                            'published': entry.get('published', ''),
                            'category': category,
                            'source': feed.feed.get('title', url),
                        }
                        
                        # HTMLタグを除去
                        article['description'] = article['description'][:200]  # 最初の200文字
                        
                        # 重複チェック
                        article_hash = hashlib.md5(
                            (article['title'] + article['link']).encode()
                        ).hexdigest()
                        
                        if article_hash not in self.seen_hashes:
                            self.seen_hashes.add(article_hash)
                            self.news_items.append(article)
                            total_articles += 1
                    
                    print(f"  ✓ {len(feed.entries[:10])} 件取得")
                    
                except Exception as e:
                    print(f"  ✗ エラー: {str(e)[:100]}")
        
        print(f"\n合計: {total_articles} 件の新しい記事を取得しました")
    
    def summarize_article(self, title, description):
        """
        OpenAI APIを使用して記事を要約
        
        Args:
            title (str): 記事タイトル
            description (str): 記事の説明
            
        Returns:
            dict: 要約結果（3行要約、重要度、コメント等）
        """
        # タイムアウトを避けるため、最初は試しに実行
        prompt = f"""
あなたはニュース要約の専門家です。以下のニュース記事を分析してください。

【タイトル】
{title}

【説明】
{description}

以下をJSON形式で日本語で返してください（必ずJSON形式で）：

{{
    "summary": "3行で要約（改行はなし）",
    "importance": "なぜ重要か（1-2文）",
    "impact": "今後どう影響するか（1-2文）",
    "star_rating": 3,
    "comment": "一言コメント（20文字以内）"
}}

star_rating は 1～5の整数で：
- 1: 関心度低い
- 2: やや関心あり
- 3: 中程度
- 4: かなり重要
- 5: 非常に重要

必ず有効なJSON形式で返してください。
"""
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "あなたはニュース分析の専門家です。必ずJSON形式で応答してください。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=300,
                timeout=30
            )
            
            # JSON解析
            result_text = response.choices[0].message.content
            
            # JSONを抽出（```で囲まれているかもしれない）
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]
            
            result = json.loads(result_text)
            
            # デフォルト値を設定
            return {
                'summary': result.get('summary', '要約作成中です'),
                'importance': result.get('importance', '重要度を評価中です'),
                'impact': result.get('impact', '今後の影響を評価中です'),
                'star_rating': min(max(result.get('star_rating', 3), 1), 5),
                'comment': result.get('comment', ''),
            }
            
        except json.JSONDecodeError as e:
            print(f"  JSON解析エラー: {str(e)[:100]}")
            return {
                'summary': '要約作成に失敗しました',
                'importance': '',
                'impact': '',
                'star_rating': 3,
                'comment': 'APIエラー',
            }
        except Exception as e:
            print(f"  API呼び出しエラー: {str(e)[:100]}")
            return {
                'summary': 'ネットワークエラーが発生しました',
                'importance': '',
                'impact': '',
                'star_rating': 3,
                'comment': 'エラー',
            }
    
    def process_news(self, max_per_category=5):
        """
        全てのニュースを処理して要約を生成
        
        Args:
            max_per_category (int): カテゴリごとの最大処理数
        """
        print("\n\n🤖 AI要約を生成中...")
        print("=" * 60)
        
        # カテゴリごとにグループ化
        by_category = defaultdict(list)
        for item in self.news_items[:30]:  # 全体で最大30件処理
            by_category[item['category']].append(item)
        
        processed_count = 0
        for category, items in by_category.items():
            print(f"\n📁 {category} ({len(items)}件)")
            
            for i, item in enumerate(items[:max_per_category], 1):
                print(f"  [{i}/{min(len(items), max_per_category)}] {item['title'][:50]}...")
                
                # OpenAI APIで要約を生成
                summary = self.summarize_article(item['title'], item['description'])
                
                # 結果をマージ
                item.update(summary)
                processed_count += 1
        
        print(f"\n✓ {processed_count} 件の記事を処理しました")
    
    def generate_html(self, output_dir='docs'):
        """
        Jinja2テンプレートを使用してHTMLを生成
        
        Args:
            output_dir (str): 出力先ディレクトリ
        """
        print("\n\n📝 HTMLを生成中...")
        print("=" * 60)
        
        # テンプレート環境を設定
        env = Environment(loader=FileSystemLoader('templates'))
        template = env.get_template('index.html')
        
        # カテゴリごとにニュースをグループ化
        news_by_category = defaultdict(list)
        for item in self.news_items:
            if 'summary' in item:  # 処理済みのみ
                news_by_category[item['category']].append(item)
        
        # 重要度でソート
        for category in news_by_category:
            news_by_category[category].sort(
                key=lambda x: x.get('star_rating', 0),
                reverse=True
            )
        
        # テンプレートにデータを渡す
        html_content = template.render(
            news_by_category=news_by_category,
            categories=['AI', '政治', '国際', 'テクノロジー', '教育', '地域ニュース', 'コミュニティ', '若者文化'],
            last_updated=datetime.now().strftime('%Y年%m月%d日 %H:%M'),
            total_articles=len(self.news_items)
        )
        
        # HTMLを保存
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, 'index.html')
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✓ {output_path} を生成しました")
        
        # CSSをコピー
        css_path = os.path.join(output_dir, 'style.css')
        if os.path.exists('assets/style.css'):
            with open('assets/style.css', 'r', encoding='utf-8') as f:
                css_content = f.read()
            with open(css_path, 'w', encoding='utf-8') as f:
                f.write(css_content)
            print(f"✓ {css_path} をコピーしました")
    
    def run(self):
        """メイン処理を実行"""
        print("\n" + "=" * 60)
        print("🚀 AIニュースダッシュボード - 実行開始")
        print("=" * 60)
        
        # 1. フィード読み込み
        feeds = self.load_feeds()
        
        # 2. ニュース取得
        self.fetch_feeds(feeds)
        
        # 3. AI要約生成
        self.process_news()
        
        # 4. HTML生成
        self.generate_html()
        
        print("\n" + "=" * 60)
        print("✅ 完了しました！")
        print(f"📄 生成されたファイル: docs/index.html")
        print("=" * 60 + "\n")


def main():
    """メイン関数"""
    try:
        aggregator = NewsAggregator()
        aggregator.run()
    except KeyboardInterrupt:
        print("\n\n❌ ユーザーに中断されました")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ エラーが発生しました: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
