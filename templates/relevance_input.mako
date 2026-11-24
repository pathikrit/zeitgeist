<%include file="about_me.mako"/>

<task>
This request contains questions about prediction markets from websites such as Kalshi and Polymarket.
Each question gives the title and the possible outcomes of one prediction market.
Do these steps for each prediction market:
  1. Read the title and the outcomes.
  2. Use the rules in <relevance> to find if the prediction market is relevant to the investor.
  3. If the prediction market is not relevant, select "${not_relevant}".
  4. If the prediction market is relevant, use the rules in <tags> to select one tag.

Obey these rules:
  - Select only one answer for each prediction market.
  - Use only the title and the outcomes. Do not try to find which outcome is the most probable.
  - Do not let the answer for one prediction market change the answer for a different prediction market.
</task>

<relevance>
A prediction market is relevant only if its result will have a clear and direct effect on the investments of the investor.
Be strict. If you are not sure that a prediction market is relevant, select "${not_relevant}".

The prediction markets in this list are not relevant, unless there is a clear effect on the investments of the investor:
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
