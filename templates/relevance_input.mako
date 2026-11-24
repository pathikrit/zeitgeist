<%include file="about_me.mako"/>

<task>
This request contains questions about prediction markets from websites such as Kalshi and Polymarket.
Each question gives the title and the possible outcomes of one prediction market.
Do these steps for each prediction market, in this sequence:
  1. Read the title and the outcomes.
  2. Use the rules in <relevance> to find if the prediction market is relevant to the investor.
     Do not think about the tags in this step.
  3. If the prediction market is not relevant, select "${not_relevant}". Then stop.
  4. If the prediction market is relevant, use the rules in <tags> to select one tag.

Obey these rules:
  - Select only one answer for each prediction market.
  - Use only the title and the outcomes. Do not try to find which outcome is the most probable.
  - Do not let the answer for one prediction market change the answer for a different prediction market.
</task>

<relevance>
A prediction market is relevant only if its result has a very clear effect on the investor.
Be very strict and careful.
"${not_relevant}" is the correct answer for most prediction markets.

The prediction markets in this list usually have no effect on the investor. They are relevant only if there is a good reason:
  - News about famous persons. Example: the number of posts that Elon Musk writes in one week.
  - Sports. Example: the transfer of a football player to a different team.
  - Events that are more than 10 years in the future. Example: India is the host of the Olympic Games before 2040.
  - Politics in a small economy. Example: an election in Kiribati.
    Politics in a large economy (for example China, India, the European Union or the Middle East) can be relevant.
  - Media and entertainment. Example: the song that is first in the Billboard chart this week.
  - Memecoins, eSports and NFTs.
    Large crypto assets (for example Bitcoin, Ethereum and Solana) can be relevant.
  - Bets on a price in a very short period. Example: the USD/JPY rate today at 12:00.
    Example: the price of Bitcoin at the end of the day. Example: the direction of Solana on one date.
</relevance>

<%include file="tags.mako" args="item='prediction market'"/>

<caution>
A tag gives only the subject of a prediction market. A subject does not make a prediction market relevant.
Many prediction markets have a subject from the list of tags, but have no very clear effect on the investor.
Example: an election for one seat in a parliament has the subject of "Govt" or "International". The correct answer is "${not_relevant}".
Example: a small detail about a company has the subject of "Market". The correct answer is "${not_relevant}".
</caution>
