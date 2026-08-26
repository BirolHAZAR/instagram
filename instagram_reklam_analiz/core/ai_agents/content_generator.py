# core/ai_agents/content_generator.py
"""
AI Destekli Ä°Ã§erik Ãœretici
Instagram iÃ§in Ã¶zgÃ¼n iÃ§erik fikirleri, baÅŸlÄ±klar, hashtag'ler ve post ÅŸablonlarÄ± Ã¼retir
"""

import json
import random
import re
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from core.services.openai_usage import record_openai_token_usage

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class ContentGenerator:
    """
    AI destekli iÃ§erik Ã¼retici sÄ±nÄ±fÄ±
    Instagram gÃ¶nderileri iÃ§in yaratÄ±cÄ± iÃ§erik fikirleri Ã¼retir
    """
    
    def __init__(self, api_key=None, user=None, organization=None):
        self.user = user
        self.organization = organization
        """Ä°Ã§erik Ã¼reticiyi baÅŸlat"""
        self.api_key = api_key or getattr(settings, 'OPENAI_API_KEY', None)
        self.use_openai = OPENAI_AVAILABLE and self.api_key
        self.client = OpenAI(api_key=self.api_key, timeout=60, max_retries=2) if self.use_openai else None
    
    def generate_post_ideas(self, niche, count=5, content_type='mixed'):
        """Post fikirleri Ã¼ret"""
        if self.use_openai:
            ideas = self._get_ai_post_ideas(niche, count, content_type)
        else:
            return {
                'success': False,
                'niche': niche,
                'content_type': content_type,
                'ideas': [],
                'error': 'OPENAI_API_KEY tanimli degil; sahte icerik fikri uretilmedi.',
                'generated_at': timezone.now().isoformat()
            }
        
        return {
            'success': True,
            'niche': niche,
            'content_type': content_type,
            'ideas': ideas,
            'generated_at': timezone.now().isoformat()
        }
    
    def generate_caption(self, topic, tone='friendly', length='medium', include_hashtags=True):
        """Caption Ã¼ret"""
        if self.use_openai:
            caption = self._get_ai_caption(topic, tone, length, include_hashtags)
        else:
            return {
                'success': False,
                'topic': topic,
                'tone': tone,
                'caption': '',
                'hashtags': [],
                'character_count': 0,
                'error': 'OPENAI_API_KEY tanimli degil; sahte caption uretilmedi.',
            }
        
        return {
            'success': True,
            'topic': topic,
            'tone': tone,
            'caption': caption.get('text', ''),
            'hashtags': caption.get('hashtags', []),
            'character_count': len(caption.get('text', ''))
        }
    
    def generate_hashtags(self, niche, count=15):
        """Hashtag Ã¶nerileri Ã¼ret"""
        hashtags = self._get_hashtag_suggestions(niche, count)
        
        return {
            'success': True,
            'niche': niche,
            'popular_hashtags': hashtags['popular'],
            'niche_hashtags': hashtags['niche'],
            'brand_hashtags': hashtags['brand'],
            'all_hashtags': hashtags['popular'][:5] + hashtags['niche'][:5] + hashtags['brand'][:3]
        }
    
    def generate_post_template(self, content_type, niche):
        """Post ÅŸablonu oluÅŸtur"""
        templates = {
            'reels': self._get_reels_template(niche),
            'carousel': self._get_carousel_template(niche),
            'image': self._get_image_template(niche),
            'story': self._get_story_template(niche)
        }
        
        return {
            'success': True,
            'content_type': content_type,
            'template': templates.get(content_type, templates['image'])
        }
    
    def generate_content_calendar(self, niche, days=7):
        """HaftalÄ±k iÃ§erik takvimi oluÅŸtur"""
        calendar = []
        start_date = datetime.now()
        
        content_types = ['reels', 'carousel', 'image', 'story', 'reels', 'carousel', 'image']
        topics = self._get_daily_topics(niche, days)
        
        for i in range(days):
            date = start_date + timedelta(days=i)
            calendar.append({
                'date': date.strftime('%Y-%m-%d'),
                'day': date.strftime('%A'),
                'content_type': content_types[i % len(content_types)],
                'topic': topics[i] if i < len(topics) else f"{niche} ile ilgili ipucu",
                'best_time': self._get_best_time(date.strftime('%A')),
                'status': 'planlandÄ±'
            })
        
        return {
            'success': True,
            'niche': niche,
            'days': days,
            'calendar': calendar,
            'recommendations': self._get_calendar_recommendations(niche)
        }
    
    def generate_engagement_questions(self, topic, count=5):
        """EtkileÅŸim sorularÄ± Ã¼ret"""
        questions = [
            f"Senin iÃ§in {topic} denince akla ne geliyor?",
            f"{topic} ile ilgili en sevdiÄŸin anÄ± nedir?",
            f"{topic} hakkÄ±nda en Ã§ok merak ettiÄŸin ÅŸey ne?",
            f"Bu {topic} konusunda bir uzmana sorsan ne sorardÄ±n?",
            f"{topic} ile ilgili bir ipucu versen ne verirdin?"
        ]
        
        return {
            'success': True,
            'topic': topic,
            'questions': questions[:count],
            'poll_options': self._generate_poll_options(topic)
        }
    
    def _get_ai_post_ideas(self, niche, count, content_type):
        """AI ile post fikirleri Ã¼ret"""
        try:
            prompt = f"""
{niche} niÅŸi iÃ§in Instagram {content_type} iÃ§erik fikirleri Ã¼ret.
{count} farklÄ± fikir Ã¼ret.
Her fikir ÅŸunlarÄ± iÃ§ersin:
- BaÅŸlÄ±k
- Ä°Ã§erik aÃ§Ä±klamasÄ±
- Hedef kitle
- Ã–nerilen sÃ¼re (reels iÃ§in) veya gÃ¶rsel sayÄ±sÄ± (carousel iÃ§in)

Fikirler Ã¶zgÃ¼n, trend ve etkileÅŸim odaklÄ± olsun.
JSON formatÄ±nda cevap ver.
"""
            from core.services.ai_gateway import create_chat_completion
            response = create_chat_completion(
                client=self.client, tariff_key="content-post-ideas",
                user=self.user, organization=self.organization,
                reference="content_generator.post_ideas",
                model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
                messages=[
                    {"role": "system", "content": "Sen kreatif bir iÃ§erik stratejistisin. Viral olabilecek iÃ§erik fikirleri Ã¼retiyorsun."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,
                temperature=0.8
            )
            return self._parse_ai_ideas(response.choices[0].message.content, count)
        except Exception as e:
            print(f"AI fikir Ã¼retme hatasÄ±: {str(e)}")
            return []
    
    def _get_ai_caption(self, topic, tone, length, include_hashtags):
        """AI ile caption Ã¼ret"""
        try:
            length_map = {'short': 50, 'medium': 150, 'long': 300}
            max_length = length_map.get(length, 150)
            
            prompt = f"""
Konu: {topic}
Ton: {tone}
Maksimum karakter: {max_length}

Bu konu iÃ§in Instagram caption'Ä± yaz.
Caption dikkat Ã§ekici, samimi ve harekete geÃ§irici olsun.
{'Sonuna 5-10 ilgili hashtag ekle.' if include_hashtags else ''}
"""
            from core.services.ai_gateway import create_chat_completion
            response = create_chat_completion(
                client=self.client, tariff_key="content-caption",
                user=self.user, organization=self.organization,
                reference="content_generator.caption",
                model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
                messages=[
                    {"role": "system", "content": "Sen bir sosyal medya uzmanÄ±sÄ±n. Etkileyici caption'lar yazÄ±yorsun."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=400,
                temperature=0.7
            )
            caption_text = response.choices[0].message.content
            hashtags = self._extract_hashtags(caption_text) if include_hashtags else []
            
            return {'text': caption_text, 'hashtags': hashtags}
        except Exception as e:
            print(f"AI caption hatasÄ±: {str(e)}")
            return {'text': '', 'hashtags': []}
    
    def _get_hashtag_suggestions(self, niche, count):
        """Hashtag Ã¶nerileri"""
        hashtag_db = {
            'moda': {
                'popular': ['#moda', '#stil', '#outfit', '#streetstyle', '#kombin', '#giyim', '#modatrendleri', '#ÅŸÄ±k'],
                'niche': ['#kapsÃ¼lgardÄ±rop', '#sÃ¼rdÃ¼rÃ¼lebilirmoda', '#vintage', '#secondhand', '#slowfashion'],
                'brand': ['#markaadÄ±', '#kampanya', '#indirim']
            },
            'yemek': {
                'popular': ['#yemek', '#tarif', '#lezzet', '#pratiktarifler', '#mutfak', '#evyemekleri', '#saÄŸlÄ±klÄ±beslenme'],
                'niche': ['#vegan', '#glutensiz', '#mealprep', '#fitrehber', '#ÅŸefÃ¶nerisi'],
                'brand': ['#markaadÄ±', '#lezzettÃ¼yolarÄ±', '#pratikÃ§Ã¶zÃ¼mler']
            },
            'seyahat': {
                'popular': ['#seyahat', '#gezi', '#tatil', '#kesfet', '#gezgin', '#travelgram', '#wanderlust'],
                'niche': ['#saklÄ±cennet', '#bÃ¼tÃ§eliseyahat', '#solotravel', '#roadtrip', '#yereldeneyimler'],
                'brand': ['#markaadÄ±', '#gezirehberi', '#kampanyaseyahat']
            },
            'teknoloji': {
                'popular': ['#teknoloji', '#yapayzeka', '#gadget', '#tekno', '#inovasyon', '#dijitaldÃ¶nÃ¼ÅŸÃ¼m'],
                'niche': ['#verimlilik', '#yazÄ±lÄ±m', '#donanÄ±m', '#sibergÃ¼venlik', '#bulutbiliÅŸim'],
                'brand': ['#markaadÄ±', '#teknolojihaberleri', '#Ã¼rÃ¼nincelemesi']
            },
            'fitness': {
                'popular': ['#fitness', '#spor', '#saÄŸlÄ±klÄ±yaÅŸam', '#egzersiz', '#fit', '#motivasyon', '#wellness'],
                'niche': ['#evdespor', '#pilates', '#yoga', '#kardiyo', '#aÄŸÄ±rlÄ±kÃ§alÄ±ÅŸmasÄ±'],
                'brand': ['#markaadÄ±', '#fitrehber', '#saÄŸlÄ±klÄ±ipuÃ§larÄ±']
            }
        }
        
        data = hashtag_db.get(niche, hashtag_db['moda'])
        return {
            'popular': data['popular'][:min(7, count)],
            'niche': data['niche'][:min(5, count)],
            'brand': data['brand'][:min(3, count)]
        }
    
    def _get_reels_template(self, niche):
        """Reels ÅŸablonu"""
        return {
            'title': f'{niche.capitalize()} Reels Ä°Ã§erik Åablonu',
            'duration': '30-60 saniye',
            'structure': [
                {'time': '0-3 sn', 'content': 'Dikkat Ã§ekici aÃ§Ä±lÄ±ÅŸ (soru veya ilginÃ§ gÃ¶rsel)'},
                {'time': '3-10 sn', 'content': 'Ana mesajÄ±n Ã¶zeti'},
                {'time': '10-25 sn', 'content': 'DetaylÄ± aÃ§Ä±klama veya gÃ¶sterim'},
                {'time': '25-30 sn', 'content': 'Harekete geÃ§irici mesaj (CTA)'}
            ],
            'music_suggestion': 'Trend ve enerjik mÃ¼zik',
            'caption_suggestion': 'KÄ±sa ve merak uyandÄ±rÄ±cÄ±, soru ile bitir'
        }
    
    def _get_carousel_template(self, niche):
        """Carousel ÅŸablonu"""
        return {
            'title': f'{niche.capitalize()} Karousel Ä°Ã§erik Åablonu',
            'slide_count': 5,
            'structure': [
                {'slide': 1, 'content': 'Kapak: Dikkat Ã§ekici baÅŸlÄ±k ve gÃ¶rsel'},
                {'slide': 2, 'content': 'GiriÅŸ: Konunun Ã¶zeti'},
                {'slide': 3, 'content': 'Ana iÃ§erik: Maddeler halinde bilgiler'},
                {'slide': 4, 'content': 'Ã–rnekler veya gÃ¶rseller'},
                {'slide': 5, 'content': 'Ã–zet ve CTA (yorum, kaydet, paylaÅŸ)'}
            ],
            'caption_suggestion': 'Uzun ve bilgilendirici, kaydetmeye teÅŸvik eden mesaj'
        }
    
    def _get_image_template(self, niche):
        """GÃ¶rsel ÅŸablonu"""
        return {
            'title': f'{niche.capitalize()} GÃ¶rsel Ä°Ã§erik Åablonu',
            'design_tips': [
                'YÃ¼ksek kontrast kullan',
                'Metin gÃ¶rselin %20\'sinden az olsun',
                'Marka renklerini kullan',
                'Sade ve anlaÅŸÄ±lÄ±r tasarÄ±m'
            ],
            'caption_suggestion': 'Bilgilendirici ve deÄŸer katan, soru sor'
        }
    
    def _get_story_template(self, niche):
        """Story ÅŸablonu"""
        return {
            'title': f'{niche.capitalize()} Story Ä°Ã§erik Åablonu',
            'interactive_elements': ['Anket', 'Soru kutusu', 'KaydÄ±rma Ã§ubuÄŸu', 'BaÄŸlantÄ±'],
            'duration': '5-15 saniye',
            'suggestion': 'Arka arkaya 3-5 story paylaÅŸarak hikaye anlat'
        }
    
    def _get_daily_topics(self, niche, days):
        """GÃ¼nlÃ¼k konular"""
        topics = {
            'moda': ['Kombin Ã¶nerileri', 'Trend renkler', 'AlÄ±ÅŸveriÅŸ ipuÃ§larÄ±', 'KÄ±yafet bakÄ±mÄ±', 'Sezon stilleri', 'Aksesuar seÃ§imi', 'KapsÃ¼l gardÄ±rop'],
            'yemek': ['Pratik tarifler', 'SaÄŸlÄ±klÄ± beslenme', 'Malzeme tÃ¼yolarÄ±', 'Sunum Ã¶nerileri', 'Mevsimsel yemekler', 'Diyet tarifleri', 'Mutfak dÃ¼zeni'],
            'seyahat': ['Seyahat planlamasÄ±', 'BÃ¼tÃ§eli rotalar', 'Paketleme ipuÃ§larÄ±', 'Yerel lezzetler', 'Konaklama Ã¶nerileri', 'Aktiviteler', 'GÃ¼venli seyahat']
        }
        return topics.get(niche, topics['moda'])[:days]
    
    def _get_best_time(self, day):
        """En iyi paylaÅŸÄ±m zamanÄ±"""
        times = {
            'Monday': '19:00',
            'Tuesday': '20:00',
            'Wednesday': '19:30',
            'Thursday': '20:30',
            'Friday': '21:00',
            'Saturday': '12:00',
            'Sunday': '15:00'
        }
        return times.get(day, '19:00')
    
    def _get_calendar_recommendations(self, niche):
        """Takvim Ã¶nerileri"""
        return [
            f"Haftada 3-4 {niche} iÃ§eriÄŸi paylaÅŸÄ±n",
            "PerÅŸembe ve Cuma gÃ¼nleri akÅŸam saatlerinde paylaÅŸÄ±m yapÄ±n",
            "Reels videolarÄ±na aÄŸÄ±rlÄ±k verin",
            "TakipÃ§ilerinize sorular sorarak etkileÅŸimi artÄ±rÄ±n"
        ]
    
    def _generate_poll_options(self, topic):
        """Anket seÃ§enekleri oluÅŸtur"""
        return [
            f"{topic} ile ilgili en sevdiÄŸim ÅŸey",
            f"{topic} Ã¶ÄŸrenmek istediÄŸim konu",
            f"{topic} hakkÄ±nda bir ipucu"
        ]
    
    def _parse_ai_ideas(self, response_text, count):
        """AI yanÄ±tÄ±nÄ± parse et"""
        try:
            json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
            if json_match:
                ideas = json.loads(json_match.group())
                return ideas[:count]
        except Exception as e:
            print(f"JSON parse hatasÄ±: {str(e)}")
        return []
    
    def _extract_hashtags(self, text):
        """Metinden hashtag'leri Ã§Ä±kar"""
        hashtags = re.findall(r'#\w+', text)
        return hashtags[:10]

