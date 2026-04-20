from zillow_client import ZillowClient
c = ZillowClient()
results = c.search_properties('Monroe County, PA', max_price=400000)
print(f'Found {len(results)} properties')
if results:
    print('Sample:', results[0].get('streetAddress'), results[0].get('price'))