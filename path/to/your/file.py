    for _, row in prop_df.iterrows():
        st.markdown(f'''<div class='property-card'>
            <h3>{row['property_name']}</h3>
            <p>{row['property_description']}</p>
            <p>Price: ${row['price']}</p>
            <p>Location: {row['location']}</p>
            <p>Bedrooms: {row['bedrooms']}</p>
            <p>Bathrooms: {row['bathrooms']}</p>
            <img src='{row['image_url']}' alt='Property Image' />
        </div>''')