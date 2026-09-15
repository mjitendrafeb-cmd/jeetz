# Phase 0 Reconnaissance Report

Run: 2026-09-09T15:26:34.670976+00:00 (GitHub Actions runner)

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
| CRISIL | search_results_page | 503 | 0 |  | — | — |
| CRISIL | industry_wise_list | 200 | 96,592 | text/html; charset=UTF-8 | — | — |
| India Ratings | api_search_bajaj | 200 | 2,942 | application/json; charset=utf- | — | Bajaj Finance |
| India Ratings | api_search_chola | 200 | 4,338 | application/json; charset=utf- | — | Cholamandalam |
| India Ratings | api_search_pfc | 200 | 1,664 | application/json; charset=utf- | — | Power Finance Corporation |
| India Ratings | api_pressrelease_known | 200 | 554 | application/json; charset=utf- | — | Bajaj Finance |
| India Ratings | api_bank_facility_data | 200 | 147,134 | application/json; charset=utf- | — | Bajaj Finance |
| India Ratings | api_rac_popular | 200 | 15,290 | application/json; charset=utf- | — | Bajaj Finance |
| India Ratings | api_nrac_popular | 200 | 125 | application/json; charset=utf- | — | — |
| India Ratings | api_issuer_pressreleases | 200 | 2 | application/json; charset=utf- | — | — |
| India Ratings | api_issuer_details | 200 | 1,202 | application/json; charset=utf- | — | Bajaj Finance |
| India Ratings | api_unaccepted_ratings | 400 | 301 | application/problem+json; char | — | — |
| India Ratings | api_probe_0 | 200 | 7,020 | text/html | — | — |
| India Ratings | api_search_bajaj_pr_0 | 200 | 1,248 | application/json; charset=utf- | — | Bajaj Finance |
| India Ratings | api_search_bajaj_pr_1 | 200 | 1,469 | application/json; charset=utf- | — | Bajaj Finance |
| India Ratings | api_search_bajaj_pr_2 | 200 | 705 | application/json; charset=utf- | — | Bajaj Finance |
| India Ratings | api_search_chola_pr_0 | 200 | 808 | application/json; charset=utf- | — | Cholamandalam |
| India Ratings | api_search_chola_pr_1 | 200 | 615 | application/json; charset=utf- | — | Cholamandalam |
| India Ratings | api_search_chola_pr_2 | 200 | 1,228 | application/json; charset=utf- | — | Cholamandalam |
| India Ratings | api_search_pfc_pr_0 | 200 | 626 | application/json; charset=utf- | — | Power Finance Corporation |
| India Ratings | api_search_pfc_pr_1 | 200 | 677 | application/json; charset=utf- | — | Power Finance Corporation |
| India Ratings | api_search_pfc_pr_2 | 200 | 1,093 | application/json; charset=utf- | — | Power Finance Corporation |

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
- Status: 503  |  Bytes: 0
- Capture: `captures/CRISIL/search_results_page.html`

### CRISIL / industry_wise_list
- URL: https://www.crisilratings.com/content/crisilratings/en/home/our-business/ratings/company-factsheet/industry-wise-rating-list.html
- Redirected to: https://www.crisilratings.com/en/home/our-business/ratings/company-factsheet/industry-wise-rating-list.html
- Status: 200  |  Bytes: 96,592
- Capture: `captures/CRISIL/industry_wise_list.html`

### India Ratings / api_search_bajaj
- URL: https://www.indiaratings.co.in/home/GetSearch?searchKey=Bajaj%20Finance
- Status: 200  |  Bytes: 2,942
- Capture: `captures/India_Ratings/api_search_bajaj.json`

### India Ratings / api_search_chola
- URL: https://www.indiaratings.co.in/home/GetSearch?searchKey=Cholamandalam
- Status: 200  |  Bytes: 4,338
- Capture: `captures/India_Ratings/api_search_chola.json`

### India Ratings / api_search_pfc
- URL: https://www.indiaratings.co.in/home/GetSearch?searchKey=Power%20Finance%20Corporation
- Status: 200  |  Bytes: 1,664
- Capture: `captures/India_Ratings/api_search_pfc.json`

### India Ratings / api_pressrelease_known
- URL: https://www.indiaratings.co.in/pressReleases/GetPressreleaseData_BeforeLogin?pressReleaseId=81837
- Status: 200  |  Bytes: 554
- Capture: `captures/India_Ratings/api_pressrelease_known.json`

### India Ratings / api_bank_facility_data
- URL: https://www.indiaratings.co.in/pressReleases/GetBankFacilityDataRatingLetter?pressReleaseId=81837
- Status: 200  |  Bytes: 147,134
- Capture: `captures/India_Ratings/api_bank_facility_data.json`

### India Ratings / api_rac_popular
- URL: https://www.indiaratings.co.in/pressReleases/GetRACPopularData?pressReleaseId=81837
- Status: 200  |  Bytes: 15,290
- Capture: `captures/India_Ratings/api_rac_popular.json`

### India Ratings / api_nrac_popular
- URL: https://www.indiaratings.co.in/pressReleases/GetNRACPopularData?pressReleaseId=81837
- Status: 200  |  Bytes: 125
- Capture: `captures/India_Ratings/api_nrac_popular.json`

### India Ratings / api_issuer_pressreleases
- URL: https://www.indiaratings.co.in/home/GetIssuerPressReleases?issuerId=2549
- Status: 200  |  Bytes: 2
- Capture: `captures/India_Ratings/api_issuer_pressreleases.json`

### India Ratings / api_issuer_details
- URL: https://www.indiaratings.co.in/home/GetIssuerDetails?issuerId=2549
- Status: 200  |  Bytes: 1,202
- Capture: `captures/India_Ratings/api_issuer_details.json`

### India Ratings / api_unaccepted_ratings
- URL: https://www.indiaratings.co.in/pressReleases/GetUnAcceptedIssuersRatings?issuerId=2549
- Status: 400  |  Bytes: 301
- Capture: `captures/India_Ratings/api_unaccepted_ratings.json`

### India Ratings / api_probe_0
- URL: https://www.indiaratings.co.in/api/upload
- Status: 200  |  Bytes: 7,020
- Capture: `captures/India_Ratings/api_probe_0.html`

### India Ratings / api_search_bajaj_pr_0
- URL: https://www.indiaratings.co.in/pressReleases/GetPressreleaseData_BeforeLogin?pressReleaseId=61233
- Status: 200  |  Bytes: 1,248
- Capture: `captures/India_Ratings/api_search_bajaj_pr_0.json`

### India Ratings / api_search_bajaj_pr_1
- URL: https://www.indiaratings.co.in/pressReleases/GetPressreleaseData_BeforeLogin?pressReleaseId=61732
- Status: 200  |  Bytes: 1,469
- Capture: `captures/India_Ratings/api_search_bajaj_pr_1.json`

### India Ratings / api_search_bajaj_pr_2
- URL: https://www.indiaratings.co.in/pressReleases/GetPressreleaseData_BeforeLogin?pressReleaseId=66528
- Status: 200  |  Bytes: 705
- Capture: `captures/India_Ratings/api_search_bajaj_pr_2.json`

### India Ratings / api_search_chola_pr_0
- URL: https://www.indiaratings.co.in/pressReleases/GetPressreleaseData_BeforeLogin?pressReleaseId=81861
- Status: 200  |  Bytes: 808
- Capture: `captures/India_Ratings/api_search_chola_pr_0.json`

### India Ratings / api_search_chola_pr_1
- URL: https://www.indiaratings.co.in/pressReleases/GetPressreleaseData_BeforeLogin?pressReleaseId=81884
- Status: 200  |  Bytes: 615
- Capture: `captures/India_Ratings/api_search_chola_pr_1.json`

### India Ratings / api_search_chola_pr_2
- URL: https://www.indiaratings.co.in/pressReleases/GetPressreleaseData_BeforeLogin?pressReleaseId=81943
- Status: 200  |  Bytes: 1,228
- Capture: `captures/India_Ratings/api_search_chola_pr_2.json`

### India Ratings / api_search_pfc_pr_0
- URL: https://www.indiaratings.co.in/pressReleases/GetPressreleaseData_BeforeLogin?pressReleaseId=35181
- Status: 200  |  Bytes: 626
- Capture: `captures/India_Ratings/api_search_pfc_pr_0.json`

### India Ratings / api_search_pfc_pr_1
- URL: https://www.indiaratings.co.in/pressReleases/GetPressreleaseData_BeforeLogin?pressReleaseId=68188
- Status: 200  |  Bytes: 677
- Capture: `captures/India_Ratings/api_search_pfc_pr_1.json`

### India Ratings / api_search_pfc_pr_2
- URL: https://www.indiaratings.co.in/pressReleases/GetPressreleaseData_BeforeLogin?pressReleaseId=76305
- Status: 200  |  Bytes: 1,093
- Capture: `captures/India_Ratings/api_search_pfc_pr_2.json`
