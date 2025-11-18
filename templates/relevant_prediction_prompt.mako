<task>
You will be provided an array of questions from an online betting market
Your job is to return only the ids of questions relevant to me
</task>

<%include file="about_me.mako"/>

Some examples of things that are UNLIKELY to impact (unless a good reason is provided):
  - Celebrity gossips e.g. how many tweets would Elon tweet this month
  - Sports related e.g. Would Ronaldo be traded this season
  - Events far (10+ years) in the future: Would India host the Olympics by 2040
  - Geography e.g. election results in Kiribati is unlikely to impact my investments
    but major economies like Chinese, India, EU, MEA politics is likely to impact
  - Media e.g. what song will be in top billboard this week
  - Ignore memecoins and NFTs (but focus on major crypto themes like BTC, solana and ethereum etc)
  - Ignore essentially gambling bets on short term prices e.g. what will be USD/JPY today at 12pm

Examine each question and return a subset of ids and related topics they may impact
Topics must be few short strings like sectors or tickers or short phrases that would be impacted by this question
Generally be lenient when possible to decide whether to include an id or not
