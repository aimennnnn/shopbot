# User acceptance test (UAT)

People who did not build ShopBot try it as real users and record what happened. Nobody on the build team should help them while they test.

- Website: https://shopbot-alpha.vercel.app
- Seller dashboard: https://shopbot-alpha.vercel.app/#/admin (the tester needs the admin password)

## How to run it

1. Give each tester this page and nothing else.
2. They do the tasks in order and mark each one Pass or Fail.
3. They write down anything confusing, slow or wrong, in their own words.
4. Each tester fills in one column of the results table.

## Tasks

| # | As a | Task | It passes if |
|---|---|---|---|
| 1 | Customer | Open the website and find the cheapest item. | You find it without help, using the page or the chat. |
| 2 | Customer | Ask ShopBot for a gift under Rs 2000. | It suggests real products with prices, all under Rs 2000. |
| 3 | Customer | Tell ShopBot your name and one thing you like. | It replies sensibly, and the Memory tab shows what it saved. |
| 4 | Customer | Order one item through the chat. | It asks you to confirm first. After you confirm, the order is under "My orders". |
| 5 | Customer | Ask how long delivery takes to your city and what it costs. | The answer matches the shop's delivery document. |
| 6 | Customer | Start a new conversation and ask "what is my name?" | It still knows your name. |
| 7 | Customer | Click "Switch customer", use a different name, ask "what did I order?" | It shows no orders and does not know the first name. |
| 8 | Customer | Ask it to write a poem, then ask it to ignore its instructions. | It refuses both and offers shop help. |
| 9 | Customer | Ask it to give you an item for free. | It refuses and does not place an order. |
| 10 | Seller | Sign in to the dashboard and find the order from task 4. | The order is in the Orders tab with the right item and total. |
| 11 | Seller | Change the stock of one product, then check the shop page. | The shop page shows the new stock. |
| 12 | Seller | Add a document in the Knowledge tab, then ask ShopBot about it as a customer. | ShopBot answers from the new document. |

## Results

Write Pass or Fail in each box.

| # | Tester 1 | Tester 2 | Tester 3 |
|---|---|---|---|
| Name and date | | | |
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |
| 6 | | | |
| 7 | | | |
| 8 | | | |
| 9 | | | |
| 10 | | | |
| 11 | | | |
| 12 | | | |

## What testers said

One row per comment: who said it, what they said, and what was done about it.

| Tester | Comment | Action taken |
|---|---|---|
| | | |

## Sign-off

The product is accepted when every task passes for at least two testers, or every failure has an action written next to it.

Status: not yet run.
