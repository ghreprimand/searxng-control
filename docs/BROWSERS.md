# Using SearXNG as your default search engine

Replace `https://search.example.com` with your SearXNG URL. The search URL template is:

```
https://search.example.com/search?q=%s
```

| Browser | Steps |
|---|---|
| Chrome, Brave, Edge, Vivaldi (desktop) | Settings → Search engine → *Manage search engines and site search* → **Site search → Add** with the URL above → ⋮ → **Make default**. Tip: if you search once on your SearXNG first, it appears under *Inactive shortcuts*. Activating that one also gives you search suggestions. |
| Firefox (desktop) | Open SearXNG, click the address bar, choose the **Search** entry with a green **+** at the bottom (or right-click the address bar → *Add "Search"*), then Settings → Search → Default. |
| Chrome / Brave (Android) | Search once on your SearXNG, then Settings → Search engine → pick it under *Recently visited*. |
| Firefox (Android, iOS) | Settings → Search → **Add search engine** with the URL above, then select it as default. |
| Chrome / Brave (iOS) | Search once on your SearXNG, then Settings → Search Engine → *Recently visited* (Brave also has *Add Custom Search Engine*). |
| Vanadium (GrapheneOS) | No manual add. In a normal tab, search 3–5 times using SearXNG's own search box, then Settings → Search engine → *Recently visited*. |
| Safari (macOS, iOS) | Doesn't support custom search engines. Use another browser or a redirect extension. |

If you use private API engines (see [API-ENGINES.md](API-ENGINES.md)), also paste the engine token into
*Preferences → General → Engine tokens* in each browser.
