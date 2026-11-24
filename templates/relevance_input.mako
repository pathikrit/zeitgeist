<%include file="about_me.mako"/>

<task>
This request contains questions about prediction markets from websites such as Kalshi and Polymarket.
There are two questions for each prediction market. Each question gives the title and the possible outcomes of the prediction market.
  - One question asks if the prediction market is relevant to the investor. Use the rules in <relevance> to answer.
  - One question asks for the tag of the prediction market. Use the rules in <tags> to answer.

Obey these rules:
  - Use only the title and the outcomes. Do not try to find which outcome is the most probable.
  - Answer each question independently. A tag does not make a prediction market relevant.
  - Do not let the answer for one prediction market change the answer for a different prediction market.
</task>

<relevance>
A prediction market is relevant only if it is very clear that its result will change the investments of the investor.
Be very strict. Most prediction markets are not relevant.
If you are not sure that a prediction market is relevant, answer that it is not relevant.

The prediction markets in this list are not relevant, unless there is a very clear effect on the investments of the investor:
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
