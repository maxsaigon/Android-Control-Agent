# Campaign Strategy Guide

## Campaign Types

### 1. Grow Followers
- **Platforms**: TikTok, Instagram
- **Actions**: Follow/unfollow, engage in niche communities, comment on popular posts
- **AI Decision**: Target accounts by niche, engagement rate, follower count overlap

### 2. Increase Engagement  
- **Platforms**: All
- **Actions**: Like, comment, share/repost
- **AI Decision**: Content quality scoring, optimal timing

### 3. Brand Awareness
- **Platforms**: Facebook, YouTube, TikTok
- **Actions**: Post creation, share content, engage with industry hashtags
- **AI Decision**: Content calendar, hashtag strategy, cross-posting

## Daily Planning Algorithm

```
Input: campaign goals, device list, account health
Output: ordered list of tasks per device per day

1. Assess each account health score
2. Calculate remaining action quota
3. Prioritize platforms by campaign goal
4. Generate action sequence:
   a. Start with warmup (5-10 min browse)
   b. Interleave actions (like → browse → comment → browse)
   c. Spread across active hours
   d. Never consecutive same-action
5. Submit tasks to Scheduler
```

## Anti-Ban Coordination

- Max 1 platform active per device at a time
- Stagger platform switches by 5-15 min
- If any platform shows warning signs → pause ALL platforms on that device for 2h
- New accounts get progressive warmup (see ai-brain SKILL.md §3.3)
