# Phase 0 Reconnaissance Report

Run: 2026-09-09T15:22:34.293735+00:00 (GitHub Actions runner)

Plain HTTP only, no browser. `Entities found` means the raw HTML already
contains that entity's name — where true for a listing page, a browser is
probably unnecessary for discovery.

| Source | Target | Status | Bytes | Type | Frameworks | Entities in raw HTML |
|---|---|---|---|---|---|---|
| CRISIL | robots | 200 | 117,459 | text/plain; charset=UTF-8 | — | — |
| CRISIL | listing_news_views | 200 | 57,520 | text/html; charset=UTF-8 | — | — |
| CRISIL | rationale_bajaj_finance | 200 | 831,635 | text/html; charset=UTF-8 | — | Bajaj Finance |
| CRISIL | rationale_bajaj_finance_mar | 200 | 869,190 | text/html; charset=UTF-8 | — | Bajaj Finance |
| CRISIL | ratings_search_page | 200 | 66,579 | text/html; charset=UTF-8 | — | — |
| ICRA | robots | 200 | 4,671 | text/html; charset=utf-8 | — | — |
| ICRA | rating_action_index | 200 | 164,381 | text/html; charset=utf-8 | DataTables | Cholamandalam |
| ICRA | rationale_chola_pdf | 200 | 2,495,048 | application/pdf | — | — |
| ICRA | rationale_chola_pdf_2 | 200 | 1,119,524 | application/pdf | — | — |
| ICRA | home | 200 | 247,419 | text/html; charset=utf-8 | — | Cholamandalam |
| India Ratings | robots | 200 | 267 | text/plain | WordPress | — |
| India Ratings | rating_actions | 200 | 7,020 | text/html | — | — |
| India Ratings | bundle_main | 200 | 2,504,416 | text/javascript | Angular, DataTables | — |
| India Ratings | bundle_scripts | 200 | 410,142 | text/javascript | — | — |
| CRISIL | search_results_page | 500 | 80,578 | text/html;charset=utf-8 | — | — |
| CRISIL | industry_wise_list | 200 | 96,592 | text/html; charset=UTF-8 | — | — |
| India Ratings | api_search_bajaj | 200 | 2 | application/json; charset=utf- | — | — |
| India Ratings | api_search_chola | 200 | 2 | application/json; charset=utf- | — | — |
| India Ratings | api_search_pfc | 200 | 2 | application/json; charset=utf- | — | — |
| India Ratings | api_generic_search | 200 | 2,942 | application/json; charset=utf- | — | Bajaj Finance |
| India Ratings | api_probe_0 | 200 | 7,020 | text/html | — | — |

## Details

### CRISIL / robots
- URL: https://www.crisilratings.com/robots.txt
- Status: 200  |  Bytes: 117,459
- Capture: `captures/CRISIL/robots.txt`
- Sitemaps: https://www.crisilratings.com/sitemap.xml

### CRISIL / listing_news_views
- URL: https://www.crisilratings.com/en/home/our-businesses/ratings/credit-ratings-news-and-views.html
- Redirected to: https://www.crisilratings.com/en/errors/404-error.html
- Status: 200  |  Bytes: 57,520
- Capture: `captures/CRISIL/listing_news_views.html`

### CRISIL / rationale_bajaj_finance
- URL: https://www.crisilratings.com/mnt/winshare/Ratings/RatingList/RatingDocs/BajajFinanceLimited_April%2028_%202026_RR_394504.html
- Status: 200  |  Bytes: 831,635
- Capture: `captures/CRISIL/rationale_bajaj_finance.html`

### CRISIL / rationale_bajaj_finance_mar
- URL: https://www.crisil.com/mnt/winshare/Ratings/RatingList/RatingDocs/BajajFinanceLimited_March%2024_%202026_RR_388205.html
- Status: 200  |  Bytes: 869,190
- Capture: `captures/CRISIL/rationale_bajaj_finance_mar.html`

### CRISIL / ratings_search_page
- URL: https://www.crisilratings.com/en/home/our-business/ratings/company-factsheet.html
- Status: 200  |  Bytes: 66,579
- Capture: `captures/CRISIL/ratings_search_page.html`

### ICRA / robots
- URL: https://www.icra.in/robots.txt
- Redirected to: https://www.icra.in/Home/SessionTimeOut
- Status: 200  |  Bytes: 4,671
- Capture: `captures/ICRA/robots.html`

### ICRA / rating_action_index
- URL: https://www.icra.in/RatingAction/Index
- Redirected to: https://www.icra.in/Home/CustomError404?aspxerrorpath=/RatingAction/Index
- Status: 200  |  Bytes: 164,381
- Capture: `captures/ICRA/rating_action_index.html`

### ICRA / rationale_chola_pdf
- URL: https://www.icra.in/Rating/GetRationalReportFilePdf?id=141344
- Status: 200  |  Bytes: 2,495,048
- Capture: `captures/ICRA/rationale_chola_pdf.pdf`

### ICRA / rationale_chola_pdf_2
- URL: https://www.icra.in/Rating/GetRationalReportFilePdf?id=133118
- Status: 200  |  Bytes: 1,119,524
- Capture: `captures/ICRA/rationale_chola_pdf_2.pdf`

### ICRA / home
- URL: https://www.icra.in/
- Status: 200  |  Bytes: 247,419
- Capture: `captures/ICRA/home.html`

### India Ratings / robots
- URL: https://www.indiaratings.co.in/robots.txt
- Status: 200  |  Bytes: 267
- Capture: `captures/India_Ratings/robots.txt`

### India Ratings / rating_actions
- URL: https://www.indiaratings.co.in/rating-actions
- Status: 200  |  Bytes: 7,020
- Capture: `captures/India_Ratings/rating_actions.html`

### India Ratings / bundle_main
- URL: https://www.indiaratings.co.in/main.b0be7d594b374f3a.js
- Status: 200  |  Bytes: 2,504,416
- Capture: `captures/India_Ratings/bundle_main.js`
- API-ish paths seen in HTML:
  - `/api/upload`

### India Ratings / bundle_scripts
- URL: https://www.indiaratings.co.in/scripts.dc77230fe30c274f.js
- Status: 200  |  Bytes: 410,142
- Capture: `captures/India_Ratings/bundle_scripts.js`

### CRISIL / search_results_page
- URL: https://www.crisilratings.com/content/crisilratings/en/home/our-business/ratings/ratings-search-results.html?searchKey=Bajaj+Finance
- Redirected to: https://www.crisilratings.com/en/home/our-business/ratings/ratings-search-results.html?searchKey=Bajaj+Finance
- Status: 500  |  Bytes: 80,578
- Capture: `captures/CRISIL/search_results_page.html`

### CRISIL / industry_wise_list
- URL: https://www.crisilratings.com/content/crisilratings/en/home/our-business/ratings/company-factsheet/industry-wise-rating-list.html
- Redirected to: https://www.crisilratings.com/en/home/our-business/ratings/company-factsheet/industry-wise-rating-list.html
- Status: 200  |  Bytes: 96,592
- Capture: `captures/CRISIL/industry_wise_list.html`

### India Ratings / api_search_bajaj
- URL: https://www.indiaratings.co.in/home/GetSearchIssuerData_PressRelease?searchKey=Bajaj%20Finance&noOfShowEntry=10
- Status: 200  |  Bytes: 2
- Capture: `captures/India_Ratings/api_search_bajaj.json`

### India Ratings / api_search_chola
- URL: https://www.indiaratings.co.in/home/GetSearchIssuerData_PressRelease?searchKey=Cholamandalam&noOfShowEntry=10
- Status: 200  |  Bytes: 2
- Capture: `captures/India_Ratings/api_search_chola.json`

### India Ratings / api_search_pfc
- URL: https://www.indiaratings.co.in/home/GetSearchIssuerData_PressRelease?searchKey=Power%20Finance%20Corporation&noOfShowEntry=10
- Status: 200  |  Bytes: 2
- Capture: `captures/India_Ratings/api_search_pfc.json`

### India Ratings / api_generic_search
- URL: https://www.indiaratings.co.in/home/GetSearch?searchKey=Bajaj%20Finance
- Status: 200  |  Bytes: 2,942
- Capture: `captures/India_Ratings/api_generic_search.json`

### India Ratings / api_probe_0
- URL: https://www.indiaratings.co.in/api/upload
- Status: 200  |  Bytes: 7,020
- Capture: `captures/India_Ratings/api_probe_0.html`
